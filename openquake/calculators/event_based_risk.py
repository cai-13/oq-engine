# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2015-2020 GEM Foundation
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

import logging
import operator
import numpy

from openquake.baselib.general import AccumDict
from openquake.baselib.python3compat import zip, encode
from openquake.hazardlib.stats import set_rlzs_stats
from openquake.risklib import riskinput, riskmodels
from openquake.calculators import base, post_risk
from openquake.calculators.export.loss_curves import get_loss_builder

U8 = numpy.uint8
U16 = numpy.uint16
U32 = numpy.uint32
F32 = numpy.float32
F64 = numpy.float64
getweight = operator.attrgetter('weight')


def event_based_risk(riskinputs, param, monitor):
    """
    :param riskinputs:
        :class:`openquake.risklib.riskinput.RiskInput` objects
    :param param:
        a dictionary of parameters
    :param monitor:
        :class:`openquake.baselib.performance.Monitor` instance
    :returns:
        a dictionary of numpy arrays of shape (L, R)
    """
    crmodel = monitor.read('crmodel')
    L = len(crmodel.lti)
    tempname = param['tempname']
    for ri in riskinputs:
        with monitor('getting hazard'):
            ri.hazard_getter.init()
            hazard = ri.hazard_getter.get_hazard()
        mon = monitor('build risk curves', measuremem=False)
        A = len(ri.aids)
        R = ri.hazard_getter.num_rlzs
        try:
            avg = numpy.zeros((A, R, L), F32)
        except MemoryError:
            raise MemoryError(
                'Building array avg of shape (%d, %d, %d)' % (A, R, L))
        result = dict(aids=ri.aids, avglosses=avg)
        acc = AccumDict()  # accumulator eidx -> agglosses
        aid2idx = {aid: idx for idx, aid in enumerate(ri.aids)}
        if 'builder' in param:
            builder = param['builder']
            P = len(builder.return_periods)
            all_curves = numpy.zeros((A, R, P), builder.loss_dt)
        # update the result dictionary and the agg array with each output
        for out in ri.gen_outputs(crmodel, monitor, tempname, hazard):
            if len(out.eids) == 0:  # this happens for sites with no events
                continue
            r = out.rlzi
            agglosses = numpy.zeros((len(out.eids), L), F32)
            for l, loss_type in enumerate(crmodel.loss_types):
                loss_ratios = out[loss_type]
                if loss_ratios is None:  # for GMFs below the minimum_intensity
                    continue
                avalues = riskmodels.get_values(loss_type, ri.assets)
                for a, asset in enumerate(ri.assets):
                    aval = avalues[a]
                    aid = asset['ordinal']
                    idx = aid2idx[aid]
                    ratios = loss_ratios[a]  # length E

                    # average losses
                    avg[idx, r, l] = (
                        ratios.sum(axis=0) * param['ses_ratio'] * aval)
                    # agglosses
                    agglosses[:, l] += ratios * aval
                    if 'builder' in param:
                        with mon:  # this is the heaviest part
                            try:
                                all_curves[idx, r][loss_type] = (
                                    builder.build_curve(aval, ratios, r))
                            except ValueError:
                                pass  # not enough event to compute the curve

            # NB: I could yield the agglosses per output, but then I would
            # have millions of small outputs with big data transfer and slow
            # saving time
            acc += dict(zip(out.eids, agglosses))

        if 'builder' in param:
            result['curves-rlzs'], result['curves-stats'] = builder.pair(
                all_curves, param['stats'])
            if R > 1 and param['individual_curves'] is False:
                del result['curves-rlzs']

        # store info about the GMFs, must be done at the end
        result['agglosses'] = (numpy.array(list(acc)),
                               numpy.array(list(acc.values())))
        yield result


@base.calculators.add('event_based_risk')
class EbrCalculator(base.RiskCalculator):
    """
    Event based PSHA calculator generating the total losses by taxonomy
    """
    core_task = event_based_risk
    is_stochastic = True
    precalc = 'event_based'
    accept_precalc = ['event_based', 'event_based_risk', 'ebrisk']

    def pre_execute(self):
        oq = self.oqparam
        super().pre_execute()
        parent = self.datastore.parent
        if not oq.ground_motion_fields:
            return  # this happens in the reportwriter

        self.L = len(self.crmodel.lti)
        self.T = len(self.assetcol.tagcol)
        self.A = len(self.assetcol)
        if parent:
            self.datastore['full_lt'] = parent['full_lt']
            self.events = parent['events']['id']
            logging.info('There are %d ruptures and %d events',
                         len(parent['ruptures']), len(self.events))
        else:
            self.events = self.datastore['events']['id']
        if oq.return_periods != [0]:
            # setting return_periods = 0 disable loss curves
            eff_time = oq.investigation_time * oq.ses_per_logic_tree_path
            if eff_time < 2:
                logging.warning(
                    'eff_time=%s is too small to compute loss curves',
                    eff_time)
            else:
                self.param['builder'] = get_loss_builder(
                    parent if parent else self.datastore,
                    oq.return_periods, oq.loss_dt())
        # sorting the eids is essential to get the epsilons in the right
        # order (i.e. consistent with the one used in ebr from ruptures)
        self.riskinputs = self.build_riskinputs('gmf')
        self.param['tempname'] = riskinput.cache_epsilons(
            self.datastore, oq, self.assetcol, self.crmodel, self.E)
        self.param['avg_losses'] = oq.avg_losses
        self.param['ses_ratio'] = oq.ses_ratio
        self.param['stats'] = list(oq.hazard_stats().items())
        self.taskno = 0
        self.start = 0
        avg_losses = oq.avg_losses
        if avg_losses:
            self.dset = self.datastore.create_dset(
                'avg_losses-rlzs', F32, (self.A, self.R, self.L))
        self.agglosses = numpy.zeros((self.E, self.L), F32)
        if 'builder' in self.param:
            self.build_datasets(self.param['builder'])
        if parent:
            parent.close()  # avoid concurrent reading issues

    def build_datasets(self, builder):
        oq = self.oqparam
        R = len(builder.weights)
        stats = self.param['stats']
        A = self.A
        S = len(stats)
        P = len(builder.return_periods)
        L = self.L
        if oq.individual_curves or R == 1:
            self.datastore.create_dset('curves-rlzs', F32, (A, R, P, L))
            self.datastore.set_shape_attrs(
                'curves-rlzs',
                assets=self.assetcol['id'],
                rlzs=numpy.arange(R),
                return_periods=builder.return_periods,
                loss_types=oq.loss_names)
        if R > 1:
            self.datastore.create_dset('curves-stats', F32, (A, S, P, L))
            self.datastore.set_shape_attrs(
                'curves-stats',
                assets=self.assetcol['id'],
                stat=[encode(name) for (name, func) in stats],
                return_periods=builder.return_periods,
                loss_types=oq.loss_names
            )

    def save_losses(self, dic):
        """
        Save the event loss tables incrementally.

        :param dic:
            dictionary with agglosses, avglosses
        """
        idxs, agglosses = dic.pop('agglosses')
        if len(idxs):
            self.agglosses[idxs] += agglosses
        aids = dic.pop('aids')
        if self.oqparam.avg_losses:
            self.dset[aids, :, :] = dic.pop('avglosses')
        self._save_curves(dic, aids)
        self.taskno += 1

    def _save_curves(self, dic, aids):
        for key in ('curves-rlzs', 'curves-stats'):
            array = dic.get(key)  # shape (A, S, P)
            if array is not None:
                shp = array.shape + (self.L,)
                self.datastore[key][aids, ...] = array.view(F32).reshape(shp)

    def combine(self, dummy, res):
        """
        :param dummy: unused parameter
        :param res: a result dictionary
        """
        with self.monitor('saving losses', measuremem=True):
            self.save_losses(res)
        return 1

    def post_execute(self, result):
        """
        Save risk data and build the aggregate loss curves
        """
        oq = self.oqparam
        logging.info('Saving event loss table')
        with self.monitor('saving event loss table', measuremem=True):
            out = []
            for eid, losses in zip(self.events, self.agglosses):
                if losses.sum():
                    out.append((eid, 0) + tuple(losses))
            arr = numpy.array(out, oq.alt_dt())
            self.datastore.create_dframe(
                'agg_loss_table', [(n, arr[n]) for n in arr.dtype.names])
        if oq.avg_losses:
            set_rlzs_stats(self.datastore, 'avg_losses',
                           asset_id=self.assetcol['id'],
                           loss_type=oq.loss_names)
        post_risk.PostRiskCalculator(oq, self.datastore.calc_id).run()
