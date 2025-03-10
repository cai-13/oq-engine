# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2015-2021 GEM Foundation
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

import os
import gzip
import unittest
import numpy
from openquake.baselib import parallel, general, config
from openquake.baselib.python3compat import decode
from openquake.hazardlib import lt
from openquake.commonlib import readinput
from openquake.calculators.views import view
from openquake.calculators.export import export
from openquake.calculators.extract import extract
from openquake.calculators.getters import get_slice_by_g
from openquake.calculators.tests import CalculatorTestCase, NOT_DARWIN
from openquake.qa_tests_data.classical import (
    case_1, case_2, case_3, case_4, case_5, case_6, case_7, case_8, case_9,
    case_10, case_11, case_12, case_13, case_14, case_15, case_16, case_17,
    case_18, case_19, case_20, case_21, case_22, case_23, case_24, case_25,
    case_26, case_27, case_28, case_29, case_30, case_31, case_32, case_33,
    case_34, case_35, case_36, case_37, case_38, case_39, case_40, case_41,
    case_42, case_43, case_44, case_45, case_46, case_47, case_48, case_49,
    case_50, case_51, case_52, case_53, case_54, case_55, case_56, case_57,
    case_58, case_59, case_60, case_61, case_62, case_63, case_64)

aac = numpy.testing.assert_allclose


def check_disagg_by_src(dstore):
    """
    Make sure that by composing disagg_by_src one gets the hazard curves
    """
    extract(dstore, 'disagg_by_src?lvl_id=-1')  # check not broken
    mean = dstore.sel('hcurves-stats', stat='mean')[:, 0]  # N, M, L
    dbs = dstore.sel('disagg_by_src')  # N, R, M, L, Ns
    poes = general.pprod(dbs, axis=4)  # N, R, M, L
    weights = dstore['weights'][:]
    mean2 = numpy.einsum('sr...,r->s...', poes, weights)  # N, M, L
    aac(mean, mean2, atol=1E-6)


def get_dists(dstore):
    dic = general.AccumDict(accum=[])  # site_id -> distances
    rup = dstore['rup']
    for sids, dsts in zip(rup['sids_'], rup['rrup_']):
        for sid, dst in zip(sids, dsts):
            dic[sid].append(int(round(dst)))
    return {sid: sorted(dsts, reverse=True) for sid, dsts in dic.items()}


class ClassicalTestCase(CalculatorTestCase):

    def assert_curves_ok(self, expected, test_dir, delta=None, **kw):
        kind = kw.pop('kind', '')
        self.run_calc(test_dir, 'job.ini', **kw)
        ds = self.calc.datastore
        got = (export(('hcurves/' + kind, 'csv'), ds) +
               export(('hmaps/' + kind, 'csv'), ds) +
               export(('uhs/' + kind, 'csv'), ds))
        self.assertEqual(len(expected), len(got), str(got))
        for fname, actual in zip(expected, got):
            self.assertEqualFiles('expected/%s' % fname, actual,
                                  delta=delta)
        return got

    def test_case_1(self):
        self.assert_curves_ok(
            ['hazard_curve-PGA.csv', 'hazard_curve-SA(0.1).csv'],
            case_1.__file__)

        if parallel.oq_distribute() != 'no':
            info = view('job_info', self.calc.datastore)
            self.assertIn('task', info)
            self.assertIn('sent', info)
            self.assertIn('received', info)

            slow = view('task:classical:-1', self.calc.datastore)
            self.assertIn('taskno', slow)
            self.assertIn('duration', slow)
            self.assertIn('sources', slow)

        # there is a single source
        self.assertEqual(len(self.calc.datastore['source_info']), 1)

        # check npz export
        export(('hcurves', 'npz'), self.calc.datastore)

        # check extraction
        sitecol = extract(self.calc.datastore, 'sitecol')
        self.assertEqual(len(sitecol.array), 1)

        # check minimum_magnitude discards the source
        with self.assertRaises(RuntimeError) as ctx:
            self.run_calc(case_1.__file__, 'job.ini', minimum_magnitude='4.5')
        self.assertEqual(str(ctx.exception), 'All sources were discarded!?')

    def test_wrong_smlt(self):
        with self.assertRaises(lt.LogicTreeError):
            self.run_calc(case_1.__file__, 'job_wrong.ini')

    def test_sa_period_too_big(self):
        imtls = '{"SA(4.1)": [0.1, 0.4, 0.6]}'
        with self.assertRaises(ValueError) as ctx:
            self.run_calc(
                case_1.__file__, 'job.ini',
                intensity_measure_types_and_levels=imtls)
        self.assertEqual(
            'SA(4.1) is out of the period range defined for [SadighEtAl1997]',
            str(ctx.exception))

    def test_case_2(self):
        self.run_calc(case_2.__file__, 'job.ini')

        # check view inputs
        lines = view('inputs', self.calc.datastore).splitlines()
        self.assertEqual(len(lines), 9)

        [fname] = export(('hcurves', 'csv'), self.calc.datastore)
        self.assertEqualFiles('expected/hcurve.csv', fname)

        # check disagg_by_src for a single realization
        check_disagg_by_src(self.calc.datastore)

    def test_case_3(self):
        self.assert_curves_ok(
            ['hazard_curve-smltp_b1-gsimltp_b1.csv'],
            case_3.__file__)

        # checking sitecol as DataFrame
        self.calc.datastore.read_df('sitecol', 'sids')

    def test_case_4(self):
        self.assert_curves_ok(
            ['hazard_curve-smltp_b1-gsimltp_b1.csv'],
            case_4.__file__)

    def test_case_5(self):
        self.assert_curves_ok(
            ['hazard_curve-smltp_b1-gsimltp_b1.csv'],
            case_5.__file__)

    def test_case_6(self):
        self.assert_curves_ok(
            ['hazard_curve-smltp_b1-gsimltp_b1.csv'],
            case_6.__file__)

    def test_case_7(self):
        # this is a case with duplicated sources
        self.assert_curves_ok(
            ['hazard_curve-mean.csv',
             'hazard_curve-smltp_b1-gsimltp_b1.csv',
             'hazard_curve-smltp_b2-gsimltp_b1.csv'],
            case_7.__file__)

        # checking the individual hazard maps are nonzero
        iml = self.calc.datastore.sel(
            'hmaps-rlzs', imt="PGA", site_id=0).squeeze()
        aac(iml, [0.167078, 0.134646], atol=.0001)  # for the two realizations

        # exercise the warning for no output when mean_hazard_curves='false'
        self.run_calc(
            case_7.__file__, 'job.ini', mean_hazard_curves='false',
            calculation_mode='preclassical',  poes='0.1')

    def test_case_8(self):
        self.assert_curves_ok(
            ['hazard_curve-smltp_b1_b2-gsimltp_b1.csv',
             'hazard_curve-smltp_b1_b3-gsimltp_b1.csv',
             'hazard_curve-smltp_b1_b4-gsimltp_b1.csv'],
            case_8.__file__)

    def test_case_9(self):
        self.assert_curves_ok(
            ['hazard_curve-smltp_b1_b2-gsimltp_b1.csv',
             'hazard_curve-smltp_b1_b3-gsimltp_b1.csv'],
            case_9.__file__)

    def test_case_10(self):
        self.assert_curves_ok(
            ['hazard_curve-smltp_b1_b2-gsimltp_b1.csv',
             'hazard_curve-smltp_b1_b3-gsimltp_b1.csv'],
            case_10.__file__)

    def test_case_11(self):
        self.assert_curves_ok(
            ['hazard_curve-mean.csv',
             'hazard_curve-smltp_b1_b2-gsimltp_b1.csv',
             'hazard_curve-smltp_b1_b3-gsimltp_b1.csv',
             'hazard_curve-smltp_b1_b4-gsimltp_b1.csv',
             'quantile_curve-0.1.csv',
             'quantile_curve-0.9.csv'],
            case_11.__file__)

    def test_case_12(self):
        # test Modified GMPE
        self.assert_curves_ok(
            ['hazard_curve-smltp_b1-gsimltp_b1_b2.csv'],
            case_12.__file__)

    def test_case_13(self):
        self.assert_curves_ok(
            ['hazard_curve-mean_PGA.csv', 'hazard_curve-mean_SA(0.2).csv',
             'hazard_map-mean.csv'], case_13.__file__)

        # test recomputing the hazard maps
        self.run_calc(
            case_13.__file__, 'job.ini', exports='csv',
            hazard_calculation_id=str(self.calc.datastore.calc_id),
            gsim_logic_tree_file='', source_model_logic_tree_file='')
        [fname] = export(('hmaps', 'csv'), self.calc.datastore)
        self.assertEqualFiles('expected/hazard_map-mean.csv', fname,
                              delta=1E-5)

        csv = general.gettemp(view('extreme_sites', self.calc.datastore))
        self.assertEqualFiles('expected/extreme_sites.csv', csv)

        # test extract/hcurves/rlz-0, used by the npz exports
        haz = vars(extract(self.calc.datastore, 'hcurves'))
        self.assertEqual(sorted(haz), ['_extra', 'all', 'investigation_time'])
        self.assertEqual(
            haz['all'].dtype.names, ('lon', 'lat', 'depth', 'mean'))
        array = haz['all']['mean']
        self.assertEqual(array.dtype.names, ('PGA', 'SA(0.2)'))
        self.assertEqual(array['PGA'].dtype.names,
                         ('0.005', '0.007', '0.0098', '0.0137', '0.0192',
                          '0.0269', '0.0376', '0.0527', '0.0738', '0.103',
                          '0.145', '0.203', '0.284'))

        # test disagg_by_src in a complex case with duplicated sources
        check_disagg_by_src(self.calc.datastore)

    def test_case_14(self):
        # test classical with 2 gsims and 1 sample
        self.assert_curves_ok(['hazard_curve-rlz-000_PGA.csv'],
                              case_14.__file__)

        # test sampling use the right number of gsims by looking at
        # the poes datasets which have shape (N, L, G)
        G = 1  # and not 2
        self.calc.datastore['_poes'].shape[-1] == G

    def test_case_15(self):
        # this is a case with both splittable and unsplittable sources
        self.assert_curves_ok('''\
hazard_curve-max-PGA.csv,
hazard_curve-mean-PGA.csv
hazard_curve-std-PGA.csv
hazard_uhs-max.csv
hazard_uhs-mean.csv
hazard_uhs-std.csv
'''.split(), case_15.__file__, delta=1E-6)

        # test UHS XML export
        fnames = [f for f in export(('uhs', 'xml'), self.calc.datastore)
                  if 'mean' in f]
        self.assertEqualFiles('expected/hazard_uhs-mean-0.01.xml', fnames[0])
        self.assertEqualFiles('expected/hazard_uhs-mean-0.1.xml', fnames[1])
        self.assertEqualFiles('expected/hazard_uhs-mean-0.2.xml', fnames[2])

        # npz exports
        [fname] = export(('hmaps', 'npz'), self.calc.datastore)
        arr = numpy.load(fname)['all']
        self.assertEqual(arr['mean'].dtype.names, ('PGA',))
        [fname] = export(('uhs', 'npz'), self.calc.datastore)
        arr = numpy.load(fname)['all']
        self.assertEqual(arr['mean'].dtype.names, ('0.01', '0.1', '0.2'))

        # check deserialization of source_model_lt
        smlt = self.calc.datastore['full_lt/source_model_lt']
        exp = str(list(smlt))
        self.assertEqual('''[<Realization #0 source_model_1.xml, path=SM1, weight=0.5>, <Realization #1 source_model_2.xml, path=SM2~a3pt2b0pt8, weight=0.25>, <Realization #2 source_model_2.xml, path=SM2~a3b1, weight=0.25>]''', exp)

    def test_case_16(self):   # sampling
        with unittest.mock.patch.dict(config.memory, limit=240):
            self.assert_curves_ok(
                ['hazard_curve-mean.csv',
                 'quantile_curve-0.1.csv',
                 'quantile_curve-0.9.csv'],
                case_16.__file__)

        # test that the single realization export fails because
        # individual_curves was false
        with self.assertRaises(KeyError) as ctx:
            export(('hcurves/rlz-3', 'csv'), self.calc.datastore)
        self.assertIn('hcurves-rlzs', str(ctx.exception))

    def test_case_17(self):  # oversampling
        # this is a test with 4 sources A and B with the same ID
        # sources A's are false duplicates, while the B's are true duplicates
        self.assert_curves_ok(
            ['hazard_curve-smltp_b1-gsimltp_b1-ltr_0.csv',
             'hazard_curve-smltp_b2-gsimltp_b1-ltr_1.csv',
             'hazard_curve-smltp_b2-gsimltp_b1-ltr_2.csv',
             'hazard_curve-smltp_b2-gsimltp_b1-ltr_3.csv',
             'hazard_curve-smltp_b2-gsimltp_b1-ltr_4.csv'],
            case_17.__file__)
        ids = decode(self.calc.datastore['source_info']['source_id'])
        numpy.testing.assert_equal(ids, ['A;0', 'B', 'A;1'])

    def test_case_18(self):  # GMPEtable
        self.assert_curves_ok(
            ['hazard_curve-mean_PGA.csv',
             'hazard_curve-mean_SA(0.2).csv',
             'hazard_curve-mean_SA(1.0).csv',
             'hazard_map-mean.csv',
             'hazard_uhs-mean.csv'],
            case_18.__file__, kind='stats', delta=1E-7)
        [fname] = export(('realizations', 'csv'), self.calc.datastore)
        self.assertEqualFiles('expected/realizations.csv', fname)

        if os.environ.get('TRAVIS'):
            raise unittest.SkipTest('Randomly broken on Travis')

        self.calc.datastore.close()
        self.calc.datastore.open('r')

        # check exporting a single realization in CSV and XML
        [fname] = export(('uhs/rlz-001', 'csv'),  self.calc.datastore)
        self.assertEqualFiles('expected/uhs-rlz-1.csv', fname)
        [fname] = export(('uhs/rlz-001', 'xml'),  self.calc.datastore)
        self.assertEqualFiles('expected/uhs-rlz-1.xml', fname)

        # extracting hmaps
        hmaps = extract(self.calc.datastore, 'hmaps')['all']['mean']
        self.assertEqual(hmaps.dtype.names, ('PGA', 'SA(0.2)', 'SA(1.0)'))

    def test_case_19(self):
        # test for AvgGMPE and pointsource_distance
        self.assert_curves_ok([
            'hazard_curve-mean_PGA.csv',
            'hazard_curve-mean_SA(0.1).csv',
            'hazard_curve-mean_SA(0.15).csv',
        ], case_19.__file__, delta=1E-5)

    def test_case_20(self):
        # Source geometry enumeration, apply_to_sources
        self.assert_curves_ok([
            'hazard_curve-mean-PGA.csv',
            'hazard_curve-smltp_sm1_sg1_cog1_char_complex-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_sm1_sg1_cog1_char_plane-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_sm1_sg1_cog1_char_simple-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_sm1_sg1_cog2_char_complex-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_sm1_sg1_cog2_char_plane-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_sm1_sg1_cog2_char_simple-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_sm1_sg2_cog1_char_complex-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_sm1_sg2_cog1_char_plane-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_sm1_sg2_cog1_char_simple-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_sm1_sg2_cog2_char_complex-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_sm1_sg2_cog2_char_plane-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_sm1_sg2_cog2_char_simple-gsimltp_Sad1997.csv'],
            case_20.__file__, delta=1E-7)
        # there are 3 sources x 12 sm_rlzs
        sgs = self.calc.csm.src_groups  # 7 source groups with 1 source each
        self.assertEqual(len(sgs), 7)
        dupl = sum(len(sg.sources[0].et_ids) - 1 for sg in sgs)
        self.assertEqual(dupl, 29)  # there are 29 duplicated sources

        # another way to look at the duplicated sources; protects against
        # future refactorings breaking the pandas readability of source_info
        df = self.calc.datastore.read_df('source_info', 'source_id')
        numpy.testing.assert_equal(
            list(df.index), ['SFLT1;0', 'COMFLT1;0', 'CHAR1;0', 'CHAR1;1',
                             'CHAR1;2', 'COMFLT1;1', 'SFLT1;1'])

        # check pandas readability of hcurves-rlzs and hcurves-stats
        df = self.calc.datastore.read_df('hcurves-rlzs', 'lvl')
        self.assertEqual(list(df.columns),
                         ['site_id', 'rlz_id', 'imt', 'value'])
        df = self.calc.datastore.read_df('hcurves-stats', 'lvl')
        self.assertEqual(list(df.columns),
                         ['site_id', 'stat', 'imt', 'value'])

    def test_case_21(self):
        # Simple fault dip and MFD enumeration
        self.assert_curves_ok([
            'hazard_curve-smltp_b1_mfd1_high_dip_dip30-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd1_high_dip_dip45-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd1_high_dip_dip60-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd1_low_dip_dip30-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd1_low_dip_dip45-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd1_low_dip_dip60-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd1_mid_dip_dip30-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd1_mid_dip_dip45-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd1_mid_dip_dip60-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd2_high_dip_dip30-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd2_high_dip_dip45-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd2_high_dip_dip60-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd2_low_dip_dip30-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd2_low_dip_dip45-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd2_low_dip_dip60-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd2_mid_dip_dip30-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd2_mid_dip_dip45-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd2_mid_dip_dip60-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd3_high_dip_dip30-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd3_high_dip_dip45-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd3_high_dip_dip60-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd3_low_dip_dip30-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd3_low_dip_dip45-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd3_low_dip_dip60-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd3_mid_dip_dip30-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd3_mid_dip_dip45-gsimltp_Sad1997.csv',
            'hazard_curve-smltp_b1_mfd3_mid_dip_dip60-gsimltp_Sad1997.csv'],
            case_21.__file__, delta=1E-7)

    def test_case_22(self):  # crossing date line calculation for Alaska
        # this also tests the splitting of the source model in two files
        self.assert_curves_ok([
            '/hazard_curve-mean-PGA.csv', 'hazard_curve-mean-SA(0.1)',
            'hazard_curve-mean-SA(0.2).csv', 'hazard_curve-mean-SA(0.5).csv',
            'hazard_curve-mean-SA(1.0).csv', 'hazard_curve-mean-SA(2.0).csv',
        ], case_22.__file__, delta=1E-6)

    def test_case_23(self):  # filtering away on TRT
        self.assert_curves_ok(['hazard_curve.csv'],
                              case_23.__file__, delta=1e-5)
        checksum = self.calc.datastore['/'].attrs['checksum32']
        self.assertEqual(checksum, 141487350)

    def test_case_24(self):  # UHS
        # this is a case with rjb and an hypocenter distribution
        self.assert_curves_ok([
            'hazard_curve-PGA.csv', 'hazard_curve-PGV.csv',
            'hazard_curve-SA(0.025).csv', 'hazard_curve-SA(0.05).csv',
            'hazard_curve-SA(0.1).csv', 'hazard_curve-SA(0.2).csv',
            'hazard_curve-SA(0.5).csv', 'hazard_curve-SA(1.0).csv',
            'hazard_curve-SA(2.0).csv', 'hazard_uhs.csv'],
                              case_24.__file__, delta=1E-5)
        total = sum(src.num_ruptures for src in self.calc.csm.get_sources())
        self.assertEqual(total, 780)  # 260 x 3
        # test that the number of ruptures is at max 1/3 of the the total
        # due to the collapsing of the hypocenters (rjb is depth-independent)
        self.assertEqual(len(self.calc.datastore['rup/mag']), 260)

    def test_case_25(self):  # negative depths
        self.assert_curves_ok(['hazard_curve-smltp_b1-gsimltp_b1.csv'],
                              case_25.__file__)

    def test_case_26(self):  # split YoungsCoppersmith1985MFD
        self.assert_curves_ok(['hazard_curve-rlz-000.csv'], case_26.__file__)

    def test_case_27(self):  # Nankai mutex model
        self.assert_curves_ok(['hazard_curve.csv'], case_27.__file__)
        # make sure probs_occur are stored as expected
        probs_occur = self.calc.datastore['rup/probs_occur_'][:]
        tot_probs_occur = sum(len(po) for po in probs_occur)
        self.assertEqual(tot_probs_occur, 28)  # 14 x 2

        # make sure there is an error when trying to disaggregate
        with self.assertRaises(NotImplementedError):
            hc_id = str(self.calc.datastore.calc_id)
            self.run_calc(case_27.__file__, 'job.ini',
                          hazard_calculation_id=hc_id,
                          calculation_mode='disaggregation',
                          truncation_level="3",
                          poes_disagg="0.02",
                          mag_bin_width="0.1",
                          distance_bin_width="10.0",
                          coordinate_bin_width="1.0",
                          num_epsilon_bins="6")

    def test_case_28(self):  # North Africa
        # MultiPointSource with modify MFD logic tree
        self.assert_curves_ok([
            'hazard_curve-mean-PGA.csv', 'hazard_curve-mean-SA(0.05).csv',
            'hazard_curve-mean-SA(0.1).csv', 'hazard_curve-mean-SA(0.2).csv',
            'hazard_curve-mean-SA(0.5)', 'hazard_curve-mean-SA(1.0).csv',
            'hazard_curve-mean-SA(2.0).csv'], case_28.__file__, delta=1E-6)

    def test_case_29(self):  # non parametric source with 2 KiteSurfaces

        # first test that the exported ruptures can be re-imported
        self.run_calc(case_29.__file__, 'job.ini',
                      calculation_mode='event_based',
                      ses_per_logic_tree_path='10')
        csv = extract(self.calc.datastore, 'ruptures').array
        rups = readinput.get_ruptures(general.gettemp(csv))
        self.assertEqual(len(rups), 1)

        # check what QGIS will be seeing
        aw = extract(self.calc.datastore, 'rupture_info')
        poly = gzip.decompress(aw.boundaries).decode('ascii')
        self.assertEqual(poly, '''POLYGON((0.17961 0.00000, 0.13492 0.00000, 0.08980 0.00000, 0.04512 0.00000, 0.00000 0.00000, 0.00000 0.04054, 0.00000 0.08109, 0.00000 0.12163, 0.00000 0.16217, 0.00000 0.20272, 0.00000 0.24326, 0.00000 0.28381, 0.04512 0.28381, 0.08980 0.28381, 0.13492 0.28381, 0.17961 0.28381, 0.17961 0.24326, 0.17961 0.20272, 0.17961 0.16217, 0.17961 0.12163, 0.17961 0.08109, 0.17961 0.04054, 0.17961 0.00000, 0.17961 0.10000, 0.13492 0.10000, 0.08980 0.10000, 0.04512 0.10000, 0.00000 0.10000, 0.00000 0.14054, 0.00000 0.18109, 0.00000 0.22163, 0.00000 0.26217, 0.00000 0.30272, 0.00000 0.34326, 0.00000 0.38381, 0.04512 0.38381, 0.08980 0.38381, 0.13492 0.38381, 0.17961 0.38381, 0.17961 0.34326, 0.17961 0.30272, 0.17961 0.26217, 0.17961 0.22163, 0.17961 0.18109, 0.17961 0.14054, 0.17961 0.10000))''')

        # then perform a classical calculation
        self.assert_curves_ok(['hazard_curve-PGA.csv'], case_29.__file__)

    def test_case_30(self):
        # point on the international data line
        # this is also a test with IMT-dependent weights
        if NOT_DARWIN:  # broken on macOS
            self.assert_curves_ok(['hazard_curve-PGA.csv',
                                   'hazard_curve-SA(1.0).csv'],
                                  case_30.__file__)
            # check rupdata
            nruptures = len(self.calc.datastore['rup/mag'])
            self.assertEqual(nruptures, 3202)

    def test_case_30_sampling(self):
        # IMT-dependent weights with sampling by cheating
        self.assert_curves_ok(
            ['hcurve-PGA.csv', 'hcurve-SA(1.0).csv'],
            case_30.__file__, number_of_logic_tree_samples='10')

    def test_case_31(self):
        # source specific logic tree
        self.assert_curves_ok(['hazard_curve-mean-PGA.csv',
                               'hazard_curve-std-PGA.csv'], case_31.__file__,
                              delta=1E-5)

    def test_case_32(self):
        # source specific logic tree
        self.assert_curves_ok(['hazard_curve-mean-PGA.csv'], case_32.__file__)

    def test_case_33(self):
        # directivity
        self.assert_curves_ok(['hazard_curve-mean-PGA.csv'], case_33.__file__)

    def test_case_34(self):
        # spectral averaging
        self.assert_curves_ok([
            'hazard_curve-mean-AvgSA.csv'], case_34.__file__)

    def test_case_35(self):
        # cluster
        self.assert_curves_ok(['hazard_curve-rlz-000-PGA.csv'],
                              case_35.__file__)

    def test_case_36(self):
        # test with advanced applyToSources and preclassical
        self.run_calc(case_36.__file__, 'job.ini')
        self.assertEqual(self.calc.R, 9)  # there are 9 realizations

    def test_case_37(self):
        # Christchurch
        self.assert_curves_ok(["hazard_curve-mean-PGA.csv",
                               "quantile_curve-0.16-PGA.csv",
                               "quantile_curve-0.5-PGA.csv",
                               "quantile_curve-0.84-PGA.csv"],
                              case_37.__file__)

    def test_case_38(self):
        # BC Hydro GMPEs with epistemic adjustments
        self.assert_curves_ok(["hazard_curve-mean-PGA.csv",
                               "hazard_uhs-mean.csv"],
                              case_38.__file__)

    def test_case_39(self):
        # 0-IMT-weights, pointsource_distance=0 and avg_ruptures collapsing
        self.assert_curves_ok([
            'hazard_curve-mean-PGA.csv', 'hazard_curve-mean-SA(0.1).csv',
            'hazard_curve-mean-SA(0.5).csv', 'hazard_curve-mean-SA(2.0).csv',
            'hazard_map-mean.csv'], case_39.__file__, delta=2E-5)

    def test_case_40(self):
        # NGA East
        self.assert_curves_ok([
            'hazard_curve-mean-PGV.csv', 'hazard_map-mean.csv'],
                              case_40.__file__, delta=1E-6)

    def test_case_41(self):
        # SERA Site Amplification Models including EC8 Site Classes and Geology
        self.assert_curves_ok(["hazard_curve-mean-PGA.csv",
                               "hazard_curve-mean-SA(1.0).csv"],
                              case_41.__file__)

    def test_case_42(self):
        # split/filter a long complex fault source with maxdist=1000 km
        self.assert_curves_ok(["hazard_curve-mean-PGA.csv",
                               "hazard_map-mean-PGA.csv"], case_42.__file__)

        # check pandas readability of hmaps-stats
        df = self.calc.datastore.read_df('hmaps-stats', 'site_id',
                                         dict(imt='PGA', stat='mean'))
        self.assertEqual(list(df.columns), ['stat', 'imt', 'poe', 'value'])

    def test_case_43(self):
        # this is a test for pointsource_distance and ps_grid_spacing
        self.assert_curves_ok(["hazard_curve-mean-PGA.csv",
                               "hazard_map-mean-PGA.csv"], case_43.__file__)
        self.assertEqual(self.calc.numctxs, 2986)  # number of contexts

    def test_case_44(self):
        # this is a test for shift_hypo. We computed independently the results
        # using the same input and a simpler calculator implemented in a
        # jupyter notebook
        self.assert_curves_ok(["hc-shift-hypo-PGA.csv"], case_44.__file__,
                              shift_hypo='true')
        self.assert_curves_ok(["hazard_curve-mean-PGA.csv"], case_44.__file__,
                              shift_hypo='false')

    def test_case_45(self):
        # this is a test for MMI with disagg_by_src
        self.assert_curves_ok(["hazard_curve-mean-MMI.csv"], case_45.__file__)
        self.calc.datastore.read_df('disagg_by_src', 'src_id')

    def test_case_46(self):
        # SMLT with applyToBranches
        self.assert_curves_ok(["hazard_curve-mean.csv"], case_46.__file__,
                               delta=1E-6)

    def test_case_47(self):
        # Mixture Model for Sigma using PEER (2018) Test Case 2.5b
        self.assert_curves_ok(["hazard_curve-rlz-000-PGA.csv",
                               "hazard_curve-rlz-001-PGA.csv"],
                              case_47.__file__, delta=1E-5)

    def test_case_48(self):
        # pointsource_distance effects on a simple point source.
        # This is case with 10 magnitudes and 2 hypodepths.
        # The maximum_distance is 110 km and the second site
        # was chosen very carefully, so that after the approximation
        # 3 ruptures get distances around 111 km and are discarded
        # (even if their true distances are around 109 km!)
        self.run_calc(case_48.__file__, 'job.ini')
        # 20 exact rrup distances for site 0 and site 1 respectively
        exact = numpy.array([[54.1249, 109.704],
                             [54.2632, 109.753],
                             [53.7378, 109.321],
                             [53.8517, 109.357],
                             [53.2577, 108.842],
                             [53.3404, 108.863],
                             [52.6774, 108.255],
                             [52.7076, 108.245],
                             [51.9595, 107.525],
                             [51.9044, 107.461],
                             [50.5455, 106.076],
                             [50.4445, 105.979],
                             [47.7896, 103.201],
                             [47.6827, 103.101],
                             [43.7002, 98.7525],
                             [43.5834, 98.6488],
                             [38.1556, 92.0187],
                             [38.0217, 91.9073],
                             [32.9537, 82.3458],
                             [32.7986, 82.2214]])
        dst = get_dists(self.calc.datastore)
        aac(dst[0], exact[:, 0], atol=.5)  # site 0
        aac(dst[1], exact[:, 1], atol=.5)  # site 1

        self.run_calc(case_48.__file__, 'job.ini', pointsource_distance='?')
        psdist = self.calc.oqparam.pointsource_distance
        psd = psdist.ddic['active shallow crust']
        dist_by_mag = {mag: int(psd[mag]) for mag in psd}
        self.assertEqual(list(dist_by_mag.values()),
                         [42, 47, 52, 58, 65, 72, 80, 89, 99, 110])

        # 17 approx rrup distances for site 0 and site 1 respectively
        approx = numpy.array([[54.1525, 109.711],
                              [53.7572, 109.324],
                              [53.2665, 108.84],
                              [52.6774, 108.255],
                              [52.7076, 108.245],
                              [51.9595, 107.525],
                              [51.9044, 107.461],
                              [50.5455, 106.076],
                              [50.4445, 105.979],
                              [47.7896, 103.201],
                              [47.6827, 103.101],
                              [43.7002, 98.7525],
                              [43.5834, 98.6488],
                              [38.1556, 92.0187],
                              [38.0217, 91.9073],
                              [32.9537, 82.3458],
                              [32.7986, 82.2214]])

        # approx distances from site 0 and site 1 respectively
        dst = get_dists(self.calc.datastore)
        aac(dst[0], approx[:, 0], atol=.5)  # site 0
        aac(dst[1], approx[:, 1], atol=.5)  # site 1

        # This test shows in detail what happens to the distances in presence
        # of a magnitude-dependent pointsource_distance.
    def test_case_49(self):
        # serious test of amplification + uhs
        self.assert_curves_ok(['hcurves-PGA.csv', 'hcurves-SA(0.21).csv',
                               'hcurves-SA(1.057).csv', 'uhs.csv'],
                              case_49.__file__, delta=1E-5)

    def test_case_50(self):
        # serious test of amplification + uhs
        self.assert_curves_ok(['hcurves-PGA.csv', 'hcurves-SA(1.0).csv',
                               'uhs.csv'], case_50.__file__, delta=1E-5)

    def test_case_51(self):
        # Modifiable GMPE
        self.assert_curves_ok(['hcurves-PGA.csv', 'hcurves-SA(0.2).csv',
                               'hcurves-SA(2.0).csv', 'uhs.csv'],
                              case_51.__file__)

    def test_case_52(self):
        # case with 2 GSIM realizations b1 (w=.9) and b2 (w=.1), 10 samples

        # late_weights
        self.run_calc(case_52.__file__, 'job.ini')
        haz = self.calc.datastore['hcurves-stats'][0, 0, 0, 6]
        aac(haz, 0.563831, rtol=1E-6)
        ws = extract(self.calc.datastore, 'weights')
        # sampled 8 times b1 and 2 times b2
        aac(ws, [0.029412, 0.029412, 0.029412, 0.264706, 0.264706, 0.029412,
                 0.029412, 0.264706, 0.029412, 0.029412], rtol=1E-5)

        # early_weights
        self.run_calc(case_52.__file__, 'job.ini',
                      sampling_method='early_weights')
        haz = self.calc.datastore['hcurves-stats'][0, 0, 0, 6]
        aac(haz, 0.56355, rtol=1E-6)
        ws = extract(self.calc.datastore, 'weights')
        aac(ws, [0.1] * 10)  # all equal

        # full enum, rlz-0: 0.554007, rlz-1: 0.601722
        self.run_calc(case_52.__file__, 'job.ini',
                      number_of_logic_tree_samples='0')
        haz = self.calc.datastore['hcurves-stats'][0, 0, 0, 6]
        aac(haz, 0.558779, rtol=1E-6)
        ws = extract(self.calc.datastore, 'weights')
        aac(ws, [0.9, 0.1])

    def test_case_52_bis(self):
        self.run_calc(case_52.__file__, 'job.ini',
                      sampling_method='late_latin')
        haz = self.calc.datastore['hcurves-stats'][0, 0, 0, 6]
        aac(haz, 0.558779, rtol=1E-6)
        ws = extract(self.calc.datastore, 'weights')
        # sampled 5 times b1 and 5 times b2
        aac(ws, [0.18, 0.02, 0.18, 0.18, 0.02, 0.02, 0.02, 0.02, 0.18, 0.18])

        self.run_calc(case_52.__file__, 'job.ini',
                      sampling_method='early_latin')
        haz = self.calc.datastore['hcurves-stats'][0, 0, 0, 6]
        aac(haz, 0.558779, rtol=1E-6)
        ws = extract(self.calc.datastore, 'weights')
        aac(ws, [0.1] * 10)  # equal weights

    def test_case_53(self):
        # Test case with 4-branch scaled backbone logic tree
        # (2 median, 2 stddev adjustments) using the ModifiableGMPE and the
        # period-independent adjustment factors
        self.assert_curves_ok(["hazard_curve-rlz-000-PGA.csv",
                               "hazard_curve-rlz-000-SA(0.5).csv",
                               "hazard_curve-rlz-001-PGA.csv",
                               "hazard_curve-rlz-001-SA(0.5).csv",
                               "hazard_curve-rlz-002-PGA.csv",
                               "hazard_curve-rlz-002-SA(0.5).csv",
                               "hazard_curve-rlz-003-PGA.csv",
                               "hazard_curve-rlz-003-SA(0.5).csv"],
                              case_53.__file__)

    def test_case_54(self):
        # Test case with 4-branch scaled backbone logic tree
        # (2 median, 2 stddev adjustments) using the ModifiableGMPE and the
        # period-dependent adjustment factors
        self.assert_curves_ok(["hazard_curve-rlz-000-PGA.csv",
                               "hazard_curve-rlz-000-SA(0.5).csv",
                               "hazard_curve-rlz-001-PGA.csv",
                               "hazard_curve-rlz-001-SA(0.5).csv",
                               "hazard_curve-rlz-002-PGA.csv",
                               "hazard_curve-rlz-002-SA(0.5).csv",
                               "hazard_curve-rlz-003-PGA.csv",
                               "hazard_curve-rlz-003-SA(0.5).csv"],
                              case_54.__file__)

    def test_case_55(self):
        # test with amplification function == 1
        self.assert_curves_ok(['hazard_curve-mean-PGA.csv'], case_55.__file__)
        hc_id = str(self.calc.datastore.calc_id)

        # test with amplification function == 2
        self.run_calc(case_55.__file__, 'job.ini',
                      hazard_calculation_id=hc_id,
                      amplification_csv='amplification2.csv')
        [fname] = export(('hcurves/mean', 'csv'), self.calc.datastore)
        self.assertEqualFiles('expected/ampl_curve-PGA.csv', fname)

        # test with amplification function == 2 and no levels
        self.run_calc(case_55.__file__, 'job.ini',
                      hazard_calculation_id=hc_id,
                      amplification_csv='amplification2bis.csv')
        [fname] = export(('hcurves/mean', 'csv'), self.calc.datastore)
        self.assertEqualFiles('expected/ampl_curve-bis.csv', fname)

    def test_case_56(self):
        # test with oversampling
        # there are 6 potential paths 1A 1B 1C 2A 2B 2C
        # 10 rlzs are being sampled: 1C 1A 1B 1A 1C 1A 2B 2A 2B 2A
        # rlzs_by_g is 135 2 4, 79 68 i.e. 1A*3 1B*1 1C*1, 2A*2 2B*2
        self.run_calc(case_56.__file__, 'job.ini', concurrent_tasks='0')
        [fname] = export(('hcurves/mean', 'csv'), self.calc.datastore)
        self.assertEqualFiles('expected/hcurves.csv', fname)

        self.calc.datastore['_poes'].shape
        full_lt = self.calc.datastore['full_lt']
        rlzs_by_grp = full_lt.get_rlzs_by_grp()
        numpy.testing.assert_equal(
            rlzs_by_grp['grp-00'], [[1, 3, 5], [2], [0, 4]])
        numpy.testing.assert_equal(
            rlzs_by_grp['grp-01'], [[7, 9], [6, 8]])
        # there are two slices 0:3 and 3:5 with length 3 and 2 respectively
        slc0, slc1 = get_slice_by_g(rlzs_by_grp)
        [(trt, gsims)] = full_lt.get_gsims_by_trt().items()
        self.assertEqual(len(gsims), 3)

    def test_case_57(self):
        # AvgPoeGMPE
        self.run_calc(case_57.__file__, 'job.ini')
        f1, f2 = export(('hcurves/mean', 'csv'), self.calc.datastore)
        self.assertEqualFiles('expected/hcurve_PGA.csv', f1)
        self.assertEqualFiles('expected/hcurve_SA.csv', f2)

    def test_case_58(self):
        # Logic tree with SimpleFault uncertainty on geometry and MFD (from
        # slip)

        # First calculation
        self.run_calc(case_58.__file__, 'job.ini')
        f01, f02 = export(('hcurves/rlz-000', 'csv'), self.calc.datastore)
        f03, f04 = export(('hcurves/rlz-003', 'csv'), self.calc.datastore)

        # Second calculation. Same LT structure for case 1 but with only one
        # branch for each branch set
        self.run_calc(case_58.__file__, 'job_case01.ini')
        f11, f12 = export(('hcurves/', 'csv'), self.calc.datastore)

        # Third calculation. In this case we use a source model containing one
        # source with the geometry of branch b22 and slip rate of branch b32
        self.run_calc(case_58.__file__, 'job_case02.ini')
        f21, f22 = export(('hcurves/', 'csv'), self.calc.datastore)

        # First test
        self.assertEqualFiles(f01, f11)

        # Second test
        self.assertEqualFiles(f03, f21)

    def test_case_59(self):
        # test NRCan15SiteTerm
        self.run_calc(case_59.__file__, 'job.ini')
        [f] = export(('hcurves/mean', 'csv'), self.calc.datastore)
        self.assertEqualFiles('expected/hcurve-mean.csv', f)

    def test_case_60(self):
        # pointsource approx with CampbellBozorgnia2003NSHMP2007
        # the hazard curve MUST be zero; it was not originally
        # due to a wrong dip angle of 0 instead of 90
        self.run_calc(case_60.__file__, 'job.ini')
        [f] = export(('hcurves/mean', 'csv'), self.calc.datastore)
        self.assertEqualFiles('expected/hazard_curve.csv', f)

    def test_case_61(self):
        # kite fault
        self.run_calc(case_61.__file__, 'job.ini')
        [f] = export(('hcurves/mean', 'csv'), self.calc.datastore)
        self.assertEqualFiles('expected/hcurve-mean.csv', f)

    def test_case_62(self):
        # multisurface with kite faults
        self.run_calc(case_62.__file__, 'job.ini')
        [f] = export(('hcurves/mean', 'csv'), self.calc.datastore)
        self.assertEqualFiles('expected/hcurve-mean.csv', f)    

    def test_case_63(self):
        # test soiltype
        self.run_calc(case_63.__file__, 'job.ini')
        [f] = export(('hcurves/mean', 'csv'), self.calc.datastore)
        self.assertEqualFiles('expected/hazard_curve-mean-PGA.csv', f)    

    def test_case_64(self):
        # LanzanoEtAl2016 with bas term
        self.run_calc(case_64.__file__, 'job.ini')
        [f] = export(('hcurves/mean', 'csv'), self.calc.datastore)
        self.assertEqualFiles('expected/hcurve-mean.csv', f)
