# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2013-2021 GEM Foundation
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake. If not, see <http://www.gnu.org/licenses/>.
import re
import ast
import copy
import operator
import functools
import collections
import numpy
import pandas

from openquake.baselib import hdf5
from openquake.baselib.node import Node
from openquake.baselib.general import AccumDict, cached_property, groupby
from openquake.hazardlib import valid, nrml, InvalidFile
from openquake.hazardlib.sourcewriter import obj_to_node
from openquake.risklib import scientific

U8 = numpy.uint8
U16 = numpy.uint16
U32 = numpy.uint32
F32 = numpy.float32
F64 = numpy.float64

COST_TYPE_REGEX = '|'.join(valid.cost_type.choices)
RISK_TYPE_REGEX = re.compile(
    r'(%s|occupants|fragility)_([\w_]+)' % COST_TYPE_REGEX)


def get_risk_files(inputs):
    """
    :param inputs: a dictionary key -> path name
    :returns: a pair (file_type, {risk_type: path})
    """
    rfs = {}
    job_ini = inputs['job_ini']
    for key in sorted(inputs):
        if key == 'fragility':
            # backward compatibily for .ini files with key fragility_file
            # instead of structural_fragility_file
            rfs['fragility/structural'] = inputs[
                'structural_fragility'] = inputs[key]
            del inputs['fragility']
        elif key.endswith(('_fragility', '_vulnerability', '_consequence')):
            match = RISK_TYPE_REGEX.match(key)
            if match and 'retrofitted' not in key and 'consequence' not in key:
                rfs['%s/%s' % (match.group(2), match.group(1))] = inputs[key]
            elif match is None:
                raise ValueError('Invalid key in %s: %s_file' % (job_ini, key))
    return rfs


# ########################### vulnerability ############################## #

def filter_vset(elem):
    return elem.tag.endswith('discreteVulnerabilitySet')


@obj_to_node.add('VulnerabilityFunction')
def build_vf_node(vf):
    """
    Convert a VulnerabilityFunction object into a Node suitable
    for XML conversion.
    """
    nodes = [Node('imls', {'imt': vf.imt}, vf.imls),
             Node('meanLRs', {}, vf.mean_loss_ratios),
             Node('covLRs', {}, vf.covs)]
    return Node(
        'vulnerabilityFunction',
        {'id': vf.id, 'dist': vf.distribution_name}, nodes=nodes)


class RiskFuncList(list):
    """
    A list of risk functions with attributes .id, .loss_type, .kind
    """
    def groupby_id(self, kind=None):
        """
        :param kind: if not None, filter the risk functions on that kind
        :returns: double dictionary id -> loss_type, kind -> risk_function
        """
        ddic = {}
        for riskid, riskfuncs in groupby(
                self, operator.attrgetter('id')).items():
            dic = groupby(
                riskfuncs, operator.attrgetter('loss_type', 'kind'))
            # there is a single risk function in each lst below
            if kind:
                ddic[riskid] = {(lt, k): lst[0] for (lt, k), lst in dic.items()
                                if k == kind}
            else:
                ddic[riskid] = {ltk: lst[0] for ltk, lst in dic.items()}
        return ddic


def get_risk_functions(oqparam, kind='vulnerability fragility consequence '
                       'vulnerability_retrofitted'):
    """
    :param oqparam:
        an OqParam instance
    :param kind:
        a space-separated string with the kinds of risk models to read
    :returns:
        a list of risk functions
    """
    kinds = kind.split()
    rmodels = AccumDict()
    for kind in kinds:
        for key in sorted(oqparam.inputs):
            mo = re.match('(occupants|%s)_%s$' % (COST_TYPE_REGEX, kind), key)
            if mo:
                loss_type = mo.group(1)  # the cost_type in the key
                # can be occupants, structural, nonstructural, ...
                rmodel = nrml.to_python(oqparam.inputs[key])
                if len(rmodel) == 0:
                    raise InvalidFile('%s is empty!' % oqparam.inputs[key])
                rmodels[loss_type, kind] = rmodel
                if rmodel.lossCategory is None:  # NRML 0.4
                    continue
                cost_type = str(rmodel.lossCategory)
                rmodel_kind = rmodel.__class__.__name__
                kind_ = kind.replace('_retrofitted', '')  # strip retrofitted
                if not rmodel_kind.lower().startswith(kind_):
                    raise ValueError(
                        'Error in the file "%s_file=%s": is '
                        'of kind %s, expected %s' % (
                            key, oqparam.inputs[key], rmodel_kind,
                            kind.capitalize() + 'Model'))
                if cost_type != loss_type:
                    raise ValueError(
                        'Error in the file "%s_file=%s": lossCategory is of '
                        'type "%s", expected "%s"' %
                        (key, oqparam.inputs[key],
                         rmodel.lossCategory, loss_type))
    cl_risk = oqparam.calculation_mode in ('classical', 'classical_risk')
    rlist = RiskFuncList()
    rlist.limit_states = []
    for (loss_type, kind), rm in sorted(rmodels.items()):
        if kind == 'fragility':
            for (imt, riskid), ffl in sorted(rm.items()):
                if not rlist.limit_states:
                    rlist.limit_states.extend(rm.limitStates)
                # we are rejecting the case of loss types with different
                # limit states; this may change in the future
                assert rlist.limit_states == rm.limitStates, (
                    rlist.limit_states, rm.limitStates)
                ffl.loss_type = loss_type
                ffl.kind = kind
                rlist.append(ffl)
        elif kind == 'consequence':
            for riskid, cf in sorted(rm.items()):
                rf = hdf5.ArrayWrapper(
                    cf, dict(id=riskid, loss_type=loss_type, kind=kind))
                rlist.append(rf)
        else:  # vulnerability, vulnerability_retrofitted
            # only for classical_risk reduce the loss_ratios
            # to make sure they are strictly increasing
            for (imt, riskid), rf in sorted(rm.items()):
                rf = rf.strictly_increasing() if cl_risk else rf
                rf.loss_type = loss_type
                rf.kind = kind
                rlist.append(rf)
    return rlist


loss_poe_dt = numpy.dtype([('loss', F64), ('poe', F64)])


def rescale(curves, values):
    """
    Multiply the losses in each curve of kind (losses, poes) by the
    corresponding value.

    :param curves: an array of shape (A, 2, C)
    :param values: an array of shape (A,)
    """
    A, _, C = curves.shape
    assert A == len(values), (A, len(values))
    array = numpy.zeros((A, C), loss_poe_dt)
    array['loss'] = [c * v for c, v in zip(curves[:, 0], values)]
    array['poe'] = curves[:, 1]
    return array


class RiskModel(object):
    """
    Base class. Can be used in the tests as a mock.

    :param taxonomy: a taxonomy string
    :param risk_functions: a dict (loss_type, kind) -> risk_function
    """
    time_event = None  # used in scenario_risk
    compositemodel = None  # set by get_crmodel

    def __init__(self, calcmode, taxonomy, risk_functions, **kw):
        self.calcmode = calcmode
        self.taxonomy = taxonomy
        self.risk_functions = risk_functions
        vars(self).update(kw)
        steps = kw.get('lrem_steps_per_interval')
        if calcmode in 'classical_risk':
            self.loss_ratios = {
                lt: tuple(vf.mean_loss_ratios_with_steps(steps))
                for (lt, kind), vf in risk_functions.items()}
        if calcmode == 'classical_bcr':
            self.loss_ratios_orig = {
                lt: tuple(vf.mean_loss_ratios_with_steps(steps))
                for (lt, kind), vf in risk_functions.items()
                if kind == 'vulnerability'}
            self.loss_ratios_retro = {
                lt: tuple(vf.mean_loss_ratios_with_steps(steps))
                for (lt, kind), vf in risk_functions.items()
                if kind == 'vulnerability_retrofitted'}

    @property
    def loss_types(self):
        """
        The list of loss types in the underlying vulnerability functions,
        in lexicographic order
        """
        return sorted(lt for (lt, kind) in self.risk_functions)

    def __call__(self, loss_type, assets, gmf_df, col=None, rndgen=None):
        meth = getattr(self, self.calcmode)
        res = meth(loss_type, assets, gmf_df, col, rndgen)
        return res

    def __toh5__(self):
        return self.risk_functions, {'taxonomy': self.taxonomy}

    def __fromh5__(self, dic, attrs):
        vars(self).update(attrs)
        self.risk_functions = dic

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self.taxonomy)

    # ######################## calculation methods ######################### #

    def classical_risk(self, loss_type, assets, hazard_curve,
                       col=None, rng=None):
        """
        :param str loss_type:
            the loss type considered
        :param assets:
            assets is an iterator over A
            :class:`openquake.risklib.scientific.Asset` instances
        :param hazard_curve:
            an array of poes
        :param eps:
            ignored, here only for API compatibility with other calculators
        :returns:
            a composite array (loss, poe) of shape (A, C)
        """
        n = len(assets)
        vf = self.risk_functions[loss_type, 'vulnerability']
        lratios = self.loss_ratios[loss_type]
        imls = self.hazard_imtls[vf.imt]
        values = assets['value-' + loss_type].to_numpy()
        lrcurves = numpy.array(
            [scientific.classical(vf, imls, hazard_curve, lratios)] * n)
        return rescale(lrcurves, values)

    def classical_bcr(self, loss_type, assets, hazard,
                      col=None, rng=None):
        """
        :param loss_type: the loss type
        :param assets: a list of N assets of the same taxonomy
        :param hazard: a dictionary col -> hazard curve
        :param _eps: dummy parameter, unused
        :returns: a list of triples (eal_orig, eal_retro, bcr_result)
        """
        if loss_type != 'structural':
            raise NotImplementedError(
                'retrofitted is not defined for ' + loss_type)
        n = len(assets)
        self.assets = assets
        vf = self.risk_functions[loss_type, 'vulnerability']
        imls = self.hazard_imtls[vf.imt]
        vf_retro = self.risk_functions[loss_type, 'vulnerability_retrofitted']
        curves_orig = functools.partial(
            scientific.classical, vf, imls,
            loss_ratios=self.loss_ratios_orig[loss_type])
        curves_retro = functools.partial(
            scientific.classical, vf_retro, imls,
            loss_ratios=self.loss_ratios_retro[loss_type])
        original_loss_curves = numpy.array([curves_orig(hazard)] * n)
        retrofitted_loss_curves = numpy.array([curves_retro(hazard)] * n)

        eal_original = numpy.array([scientific.average_loss(lc)
                                    for lc in original_loss_curves])

        eal_retrofitted = numpy.array([scientific.average_loss(lc)
                                       for lc in retrofitted_loss_curves])

        bcr_results = [
            scientific.bcr(
                eal_original[i], eal_retrofitted[i],
                self.interest_rate, self.asset_life_expectancy,
                asset['value-' + loss_type], asset['retrofitted'])
            for i, asset in enumerate(assets.to_records())]
        return list(zip(eal_original, eal_retrofitted, bcr_results))

    def classical_damage(self, loss_type, assets, hazard_curve,
                         col=None, rng=None):
        """
        :param loss_type: the loss type
        :param assets: a list of N assets of the same taxonomy
        :param hazard_curve: a dictionary col -> hazard curve
        :returns: an array of N x D elements

        where N is the number of points and D the number of damage states.
        """
        ffl = self.risk_functions[loss_type, 'fragility']
        hazard_imls = self.hazard_imtls[ffl.imt]
        rtime = self.risk_investigation_time or self.investigation_time
        damage = scientific.classical_damage(
            ffl, hazard_imls, hazard_curve,
            investigation_time=self.investigation_time,
            risk_investigation_time=rtime,
            steps_per_interval=self.steps_per_interval)
        res = numpy.array([a['number'] * damage for a in assets.to_records()])
        return res

    def event_based_risk(self, loss_type, assets, gmf_df, col, rndgen):
        """
        :returns: a DataFrame with columns eid, eid, loss
        """
        sid = assets['site_id']
        if loss_type == 'occupants' and self.time_event:
            val = assets['occupants_%s' % self.time_event].to_numpy()
        else:
            val = assets['value-' + loss_type].to_numpy()
        asset_df = pandas.DataFrame(dict(aid=assets.index, val=val), sid)
        vf = self.risk_functions[loss_type, 'vulnerability']
        return vf(asset_df, gmf_df, col, rndgen,
                  self.minimum_asset_loss[loss_type])

    scenario = ebrisk = scenario_risk = event_based_risk

    def scenario_damage(self, loss_type, assets, gmf_df, col,
                        rng=None):
        """
        :param loss_type: the loss type
        :param assets: a list of A assets of the same taxonomy
        :param gmf_df: a DataFrame of GMFs
        :param epsilons: dummy parameter, unused
        :returns: an array of shape (A, E, D) elements

        where N is the number of points, E the number of events
        and D the number of damage states.
        """
        gmvs = gmf_df[col].to_numpy()
        ffs = self.risk_functions[loss_type, 'fragility']
        damages = scientific.scenario_damage(ffs, gmvs).T
        return numpy.array([damages] * len(assets))

    event_based_damage = scenario_damage


# NB: the approach used here relies on the convention of having the
# names of the arguments of the RiskModel class to be equal to the
# names of the parameter in the oqparam object. This is seen as a
# feature, since it forces people to be consistent with the names,
# in the spirit of the 'convention over configuration' philosophy
def get_riskmodel(taxonomy, oqparam, **extra):
    """
    Return an instance of the correct risk model class, depending on the
    attribute `calculation_mode` of the object `oqparam`.

    :param taxonomy:
        a taxonomy string
    :param oqparam:
        an object containing the parameters needed by the RiskModel class
    :param extra:
        extra parameters to pass to the RiskModel class
    """
    extra['hazard_imtls'] = oqparam.imtls
    extra['investigation_time'] = oqparam.investigation_time
    extra['risk_investigation_time'] = oqparam.risk_investigation_time
    extra['lrem_steps_per_interval'] = oqparam.lrem_steps_per_interval
    extra['steps_per_interval'] = oqparam.steps_per_interval
    extra['time_event'] = oqparam.time_event
    extra['minimum_asset_loss'] = oqparam.minimum_asset_loss
    if oqparam.calculation_mode == 'classical_bcr':
        extra['interest_rate'] = oqparam.interest_rate
        extra['asset_life_expectancy'] = oqparam.asset_life_expectancy
    return RiskModel(oqparam.calculation_mode, taxonomy, **extra)


# ######################## CompositeRiskModel #########################

class ValidationError(Exception):
    pass


class CompositeRiskModel(collections.abc.Mapping):
    """
    A container (riskid, kind) -> riskmodel

    :param oqparam:
        an :class:`openquake.commonlib.oqvalidation.OqParam` instance
    :param fragdict:
        a dictionary riskid -> loss_type -> fragility functions
    :param vulndict:
        a dictionary riskid -> loss_type -> vulnerability function
    :param consdict:
        a dictionary riskid -> loss_type -> consequence functions
    """
    @classmethod
    # TODO: reading new-style consequences is missing
    def read(cls, dstore, oqparam):
        """
        :param dstore: a DataStore instance
        :returns: a :class:`CompositeRiskModel` instance
        """
        risklist = RiskFuncList()
        risklist.limit_states = dstore.get_attr('crm', 'limit_states')
        df = dstore.read_df('crm', ['riskid', 'loss_type'])
        for rf_json in df.riskfunc:
            rf = hdf5.json_to_obj(rf_json)
            lt = rf.loss_type
            if rf.kind == 'fragility':  # rf is a FragilityFunctionList
                risklist.append(rf)
            else:  # rf is a vulnerability function
                rf.init()
                if lt.endswith('_retrofitted'):
                    # strip _retrofitted, since len('_retrofitted') = 12
                    rf.loss_type = lt[:-12]
                    rf.kind = 'vulnerability_retrofitted'
                else:
                    rf.loss_type = lt
                    rf.kind = 'vulnerability'
                risklist.append(rf)
        crm = CompositeRiskModel(oqparam, risklist)
        crm.tmap = ast.literal_eval(dstore.get_attr('crm', 'tmap'))
        return crm

    def __init__(self, oqparam, risklist, consdict=()):
        self.oqparam = oqparam
        self.risklist = risklist  # by taxonomy
        self.consdict = consdict or {}  # new style consequences, by anything
        self.init()

    def compute_csq(self, asset, fractions, loss_type):
        """
        :param asset: asset record
        :param fractions: array of probabilies of shape (E, D)
        :param loss_type: loss type as a string
        :returns: a dict consequence_name -> array of length E
        """
        csq = {}  # cname -> values per event
        for byname, coeffs in self.consdict.items():
            # ex. byname = "losses_by_taxonomy"
            if len(coeffs):
                cname, tagname = byname.split('_by_')
                func = scientific.consequence[cname]
                cs = coeffs[asset[tagname]][loss_type]
                csq[cname] = func(cs, asset, fractions[:, 1:], loss_type)
        return csq

    def init(self):
        oq = self.oqparam
        if self.risklist:
            oq.set_risk_imts(self.risklist)
        # extract the consequences from the risk models, if any
        if 'losses_by_taxonomy' not in self.consdict:
            self.consdict['losses_by_taxonomy'] = {}
        for riskid, dic in self.risklist.groupby_id(
                kind='consequence').items():
            if dic:
                dtlist = [(lt, F32) for lt, kind in dic]
                coeffs = numpy.zeros(
                    len(self.risklist.limit_states), dtlist)
                for (lt, kind), cf in dic.items():
                    coeffs[lt] = cf
                self.consdict['losses_by_taxonomy'][riskid] = coeffs
        self.damage_states = []
        self._riskmodels = {}  # riskid -> crmodel
        if oq.calculation_mode.endswith('_bcr'):
            # classical_bcr calculator
            for riskid, risk_functions in self.risklist.groupby_id().items():
                self._riskmodels[riskid] = get_riskmodel(
                    riskid, oq, risk_functions=risk_functions)
        elif (any(rf.kind == 'fragility' for rf in self.risklist) or
              'damage' in oq.calculation_mode):
            # classical_damage/scenario_damage calculator
            if oq.calculation_mode in ('classical', 'scenario'):
                # case when the risk files are in the job_hazard.ini file
                oq.calculation_mode += '_damage'
                if 'exposure' not in oq.inputs:
                    raise RuntimeError(
                        'There are risk files in %r but not '
                        'an exposure' % oq.inputs['job_ini'])

            self.damage_states = ['no_damage'] + list(
                self.risklist.limit_states)
            for riskid, ffs_by_lt in self.risklist.groupby_id().items():
                self._riskmodels[riskid] = get_riskmodel(
                    riskid, oq, risk_functions=ffs_by_lt)
        else:
            # classical, event based and scenario calculators
            for riskid, vfs in self.risklist.groupby_id().items():
                self._riskmodels[riskid] = get_riskmodel(
                    riskid, oq, risk_functions=vfs)
        self.primary_imtls = oq.get_primary_imtls()
        self.imtls = oq.imtls
        self.lti = {}  # loss_type -> idx
        self.covs = 0  # number of coefficients of variation
        # build a sorted list with all the loss_types contained in the model
        ltypes = set()
        for rm in self.values():
            ltypes.update(rm.loss_types)
        self.loss_types = sorted(ltypes)
        self.taxonomies = set()
        self.distributions = set()
        for riskid, rm in self._riskmodels.items():
            self.taxonomies.add(riskid)
            rm.compositemodel = self
            for lt, rf in rm.risk_functions.items():
                if hasattr(rf, 'distribution_name'):
                    self.distributions.add(rf.distribution_name)
                if hasattr(rf, 'init'):  # vulnerability function
                    if oq.ignore_covs:
                        rf.covs = numpy.zeros_like(rf.covs)
                    rf.init()
                # save the number of nonzero coefficients of variation
                if hasattr(rf, 'covs') and rf.covs.any():
                    self.covs += 1
            rm.imt_by_lt = {}  # dictionary loss_type -> imt
            for lt, kind in rm.risk_functions:
                if kind in 'vulnerability fragility':
                    imt = rm.risk_functions[lt, kind].imt
                    rm.imt_by_lt[lt] = imt
        self.curve_params = self.make_curve_params()
        iml = collections.defaultdict(list)
        # ._riskmodels is empty if read from the hazard calculation
        for riskid, rm in self._riskmodels.items():
            for lt, rf in rm.risk_functions.items():
                if hasattr(rf, 'imt'):
                    iml[rf.imt].append(rf.imls[0])
        if sum(oq.minimum_intensity.values()) == 0 and iml:
            oq.minimum_intensity = {imt: min(ls) for imt, ls in iml.items()}

    def eid_dmg_dt(self):
        """
        :returns: a dtype (eid, dmg)
        """
        L = len(self.lti)
        D = len(self.damage_states)
        return numpy.dtype([('eid', U32), ('dmg', (F32, (L, D)))])

    def asset_damage_dt(self, float_dmg_dist):
        """
        :returns: a list [('aid', U32), ('eid', U32), ('lid', U8),
                          ('moderate_0', U32), ...]
        """
        dt = F32 if float_dmg_dist else U32
        dtlist = [('aid', U32), ('eid', U32), ('lid', U8)]
        for dmg in self.damage_states[1:]:
            dtlist.append((dmg, dt))
        return dtlist

    def reduce_cons_model(self, tagcol):
        """
        Convert the dictionaries tag -> coeffs in the consequence model
        into dictionaries tag index -> coeffs (one per cname)
        """
        for cname_by_tagname, dic in self.consdict.items():
            # for instance losses_by_taxonomy
            cname, tagname = cname_by_tagname.split('_by_')
            tagidx = tagcol.get_tagidx(tagname)
            newdic = {tagidx[tag]: cf for tag, cf in dic.items()
                      if tag in tagidx}  # tag in the exposure
            self.consdict[cname_by_tagname] = newdic

    @cached_property
    def taxonomy_dict(self):
        """
        :returns: a dict taxonomy string -> taxonomy index
        """
        # .taxonomy must be set by the engine
        tdict = {taxo: idx for idx, taxo in enumerate(self.taxonomy)}
        return tdict

    def get_consequences(self):
        """
        :returns: the list of available consequences
        """
        csq = []
        for cname_by_tagname, arr in self.consdict.items():
            if len(arr):
                csq.append(cname_by_tagname.split('_by_')[0])
        return csq

    def get_dmg_csq(self):
        """
        :returns: damage states (except no_damage) plus consequences
        """
        D = len(self.damage_states)
        dmgs = ['dmg_%d' % d for d in range(1, D)]
        return dmgs + self.get_consequences()

    def make_curve_params(self):
        # the CurveParams are used only in classical_risk, classical_bcr
        # NB: populate the inner lists .loss_types too
        cps = []
        for lti, loss_type in enumerate(self.loss_types):
            if self.oqparam.calculation_mode in (
                    'classical', 'classical_risk'):
                curve_resolutions = set()
                lines = []
                allratios = []
                for taxo in sorted(self):
                    rm = self[taxo]
                    rf = rm.risk_functions.get((loss_type, 'vulnerability'))
                    if rf and loss_type in rm.loss_ratios:
                        ratios = rm.loss_ratios[loss_type]
                        allratios.append(ratios)
                        curve_resolutions.add(len(ratios))
                        lines.append('%s %d' % (rf, len(ratios)))
                if len(curve_resolutions) > 1:
                    # number of loss ratios is not the same for all taxonomies:
                    # then use the longest array; see classical_risk case_5
                    allratios.sort(key=len)
                    for rm in self.values():
                        if rm.loss_ratios[loss_type] != allratios[-1]:
                            rm.loss_ratios[loss_type] = allratios[-1]
                            # logging.debug(f'Redefining loss ratios for {rm}')
                cp = scientific.CurveParams(
                    lti, loss_type, max(curve_resolutions), allratios[-1], True
                ) if curve_resolutions else scientific.CurveParams(
                    lti, loss_type, 0, [], False)
            else:  # used only to store the association l -> loss_type
                cp = scientific.CurveParams(lti, loss_type, 0, [], False)
            cps.append(cp)
            self.lti[loss_type] = lti
        return cps

    def get_loss_ratios(self):
        """
        :returns: a 1-dimensional composite array with loss ratios by loss type
        """
        lst = [('user_provided', numpy.bool)]
        for cp in self.curve_params:
            lst.append((cp.loss_type, F32, len(cp.ratios)))
        loss_ratios = numpy.zeros(1, numpy.dtype(lst))
        for cp in self.curve_params:
            loss_ratios['user_provided'] = cp.user_provided
            loss_ratios[cp.loss_type] = tuple(cp.ratios)
        return loss_ratios

    def __getitem__(self, taxo):
        return self._riskmodels[taxo]

    def get_output(self, taxo, assets, haz, sec_losses=(), rndgen=None,
                   rlz=None):
        """
        :param taxo: a taxonomy index
        :param assets: a DataFrame of assets of the given taxonomy
        :param haz: a DataFrame of GMVs on that site
        :param sec_losses: a list of SecondaryLoss instances
        :param rndgen: a MultiEventRNG instance
        :param rlz: a realization index (or None)
        :returns: a dictionary of arrays
        """
        primary = self.primary_imtls
        alias = {imt: 'gmv_%d' % i for i, imt in enumerate(primary)}
        event = hasattr(haz, 'eid')
        eids = haz.eid.to_numpy() if event else [None]
        dic = dict(eids=eids, assets=assets.to_records(), rlzi=rlz,
                   loss_types=self.loss_types, haz=haz)
        for lt in self.loss_types:
            outs = []
            rmodels, weights = self.get_rmodels_weights(lt, taxo)
            for rm in rmodels:
                imt = rm.imt_by_lt[lt]
                col = alias.get(imt, imt)
                if event:
                    outs.append(rm(lt, assets, haz, col, rndgen))
                else:  # classical
                    hcurve = haz.array[self.imtls(imt), 0]
                    outs.append(rm(lt, assets, hcurve))

            # average on the risk models (unsupported for classical_risk)
            dic[lt] = outs[0]
            if hasattr(dic[lt], 'loss'):  # event_based_risk
                if weights[0] != 1:
                    dic[lt].loss *= weights[0]
                for alt, w in zip(outs[1:], weights[1:]):
                    dic[lt].loss += alt.loss * w
            elif len(weights) > 1:  # scenario_damage
                dic[lt] = numpy.average(outs, weights=weights, axis=0)
        # compute secondary losses, if any
        # FIXME: it should be moved up, before the computation of the mean
        for sec_loss in sec_losses:
            sec_loss.update(dic, assets)
        return dic

    def get_rmodels_weights(self, loss_type, taxidx):
        """
        :returns: a list of weighted risk models for the given taxonomy index
        """
        rmodels, weights = [], []
        for key, weight in self.tmap[loss_type][taxidx]:
            rmodels.append(self._riskmodels[key])
            weights.append(weight)
        return rmodels, weights

    def __iter__(self):
        return iter(sorted(self._riskmodels))

    def __len__(self):
        return len(self._riskmodels)

    def reduce(self, taxonomies):
        """
        :param taxonomies: a set of taxonomies
        :returns: a new CompositeRiskModel reduced to the given taxonomies
        """
        new = copy.copy(self)
        new._riskmodels = {}
        for riskid, rm in self._riskmodels.items():
            if riskid in taxonomies:
                new._riskmodels[riskid] = rm
                rm.compositemodel = new
        return new

    def get_attrs(self):
        loss_types = hdf5.array_of_vstr(self.loss_types)
        limit_states = hdf5.array_of_vstr(self.damage_states[1:]
                                          if self.damage_states else [])
        attrs = dict(covs=self.covs, loss_types=loss_types,
                     limit_states=limit_states,
                     tmap=repr(getattr(self, 'tmap', [])))
        rf = next(iter(self.values()))
        if hasattr(rf, 'loss_ratios'):
            for lt in self.loss_types:
                attrs['loss_ratios_' + lt] = rf.loss_ratios[lt]
        return attrs

    def to_dframe(self):
        """
        :returns: a DataFrame containing all risk functions
        """
        dic = {'riskid': [], 'loss_type': [], 'riskfunc': []}
        for riskid, rm in self._riskmodels.items():
            for (lt, kind), rf in rm.risk_functions.items():
                dic['riskid'].append(riskid)
                dic['loss_type'].append(lt)
                dic['riskfunc'].append(hdf5.obj_to_json(rf))
        return pandas.DataFrame(dic)

    def __repr__(self):
        lines = ['%s: %s' % item for item in sorted(self.items())]
        return '<%s\n%s>' % (self.__class__.__name__, '\n'.join(lines))
