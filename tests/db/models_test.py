# Copyright (c) 2010-2012, GEM Foundation.
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake.  If not, see <http://www.gnu.org/licenses/>.


import itertools
import string
import unittest

from django.contrib.gis.geos.geometry import GEOSGeometry

from openquake import engine
from openquake import engine2
from openquake.db import models

from tests.utils import helpers


class ModelEqualsTestCase(unittest.TestCase):
    """Tests for :function:`model_equals`, a function to compare the contents
    of two Django models objects."""

    def setUp(self):
        self.org = models.Organization(
            name='test_name', address='test_address', url='http://test.com')
        self.org.save()

        # Now query two fresh copies of this record from the DB to test with:
        self.o1 = models.Organization.objects.get(id=self.org.id)
        self.o2 = models.Organization.objects.get(id=self.org.id)

    def test_model_equals(self):
        self.assertTrue(models.model_equals(self.o1, self.o2))

    def test_model_equals_with_different_values(self):
        self.o1.name = 'something different'
        self.assertFalse(models.model_equals(self.o1, self.o2))

    def test_model_equals_with_ignore(self):
        self.o1.name = 'something different'
        self.assertTrue(
            models.model_equals(self.o1, self.o2, ignore=('name',)))

    def test_model_equals_with_many_ignores(self):
        self.o1.name = 'something different'
        self.o1.url = 'http://www.somethingdiff.com'
        self.assertTrue(
            models.model_equals(self.o1, self.o2, ignore=('name', 'url')))

    def test_model_equals_ignore_id(self):
        """Comparing two models with different ids is a special case, thus a
        separate test.

        This is a special case because it is very likely that we could have
        multiple records with the same contents but different ids. An example
        of this would be two :class:`openquake.db.models.OqJobProfile`
        records that contain the exact same config parameters, just different
        database ids. """
        self.o1.id = 1
        self.o2.id = 2

        self.assertTrue(models.model_equals(self.o1, self.o2, ignore=('id',)))

    def test_model_equals_with_invalid_ignores(self):
        self.assertTrue(models.model_equals(
            self.o1, self.o2, ignore=('not_an_attr',)))

    def test__state_is_always_ignored(self):
        # Set some fake _state values on the model objects:
        self.o1._state = 'fake_state'
        self.o2._state = 'other_fake_state'

        # Sanity check: make sure _state is in the object dict.
        self.assertTrue('_state' in self.o1.__dict__)
        self.assertTrue('_state' in self.o2.__dict__)

        # Sanity check 2: Make sure the object dict _state is correctly set.
        self.assertEquals('fake_state', self.o1.__dict__['_state'])
        self.assertEquals('other_fake_state', self.o2.__dict__['_state'])

        # Now finally compare the two objects:
        self.assertTrue(models.model_equals(self.o1, self.o2))

    def test_model_equals_different_classes(self):
        gmf = models.GmfData(ground_motion=1.0)

        self.assertFalse(models.model_equals(self.o1, gmf))

    def test_model_equals_with_geometry(self):
        gmf_data_1 = models.GmfData(
            ground_motion=5.0,
            location=GEOSGeometry("POINT (30.0 10.0)"))

        gmf_data_2 = models.GmfData(
            ground_motion=5.0,
            location=GEOSGeometry("POINT (30.0 10.0)"))

        self.assertTrue(models.model_equals(gmf_data_1, gmf_data_2))

    def test_model_equals_with_different_geometry(self):
        gmf_data_1 = models.GmfData(
            ground_motion=5.0,
            location=GEOSGeometry("POINT (30.0 10.0)"))

        gmf_data_2 = models.GmfData(
            ground_motion=5.0,
            location=GEOSGeometry("POINT (30.0 10.1)"))

        self.assertFalse(models.model_equals(gmf_data_1, gmf_data_2))


class Profile4JobTestCase(helpers.DbTestCase):
    """Tests for :function:`profile4job`."""

    def test_profile4job_with_existing(self):
        # The correct job profile is found.
        job = self.setup_classic_job()
        self.assertIsNot(None, models.profile4job(job.id))

    def test_profile4job_with_non_existing(self):
        # No job profile is found, exception is raised.
        self.assertRaises(ValueError, models.profile4job, -123)


class Inputs4JobTestCase(unittest.TestCase):
    """Tests for :function:`inputs4job`."""

    sizes = itertools.count(10)
    paths = itertools.cycle(string.ascii_lowercase)

    def setUp(self):
        self.job = engine.prepare_job()

    def test_inputs4job_with_no_input(self):
        # No inputs exist, an empty list is returned.
        self.assertEqual([], models.inputs4job(self.job.id))

    def test_inputs4job_with_single_input(self):
        # The single input is returned.
        inp = models.Input(owner=self.job.owner, path=self.paths.next(),
                           input_type="exposure", size=self.sizes.next())
        inp.save()
        models.Input2job(oq_job=self.job, input=inp).save()
        self.assertEqual([inp], models.inputs4job(self.job.id))

    def test_inputs4job_with_wrong_input_type(self):
        # No input is returned.
        inp = models.Input(owner=self.job.owner, path=self.paths.next(),
                           input_type="exposure", size=self.sizes.next())
        inp.save()
        models.Input2job(oq_job=self.job, input=inp).save()
        self.assertEqual([], models.inputs4job(self.job.id, input_type="xxx"))

    def test_inputs4job_with_correct_input_type(self):
        # The exposure inputs are returned.
        inp1 = models.Input(owner=self.job.owner, path=self.paths.next(),
                            input_type="exposure", size=self.sizes.next())
        inp1.save()
        models.Input2job(oq_job=self.job, input=inp1).save()
        inp2 = models.Input(owner=self.job.owner, path=self.paths.next(),
                            input_type="rupture", size=self.sizes.next())
        inp2.save()
        models.Input2job(oq_job=self.job, input=inp2).save()
        inp3 = models.Input(owner=self.job.owner, path=self.paths.next(),
                            input_type="exposure", size=self.sizes.next())
        inp3.save()
        models.Input2job(oq_job=self.job, input=inp3).save()
        self.assertEqual([inp1, inp3],
                         models.inputs4job(self.job.id, input_type="exposure"))

    def test_inputs4job_with_wrong_path(self):
        # No input is returned.
        inp = models.Input(owner=self.job.owner, path=self.paths.next(),
                           input_type="exposure", size=self.sizes.next())
        inp.save()
        models.Input2job(oq_job=self.job, input=inp).save()
        self.assertEqual([], models.inputs4job(self.job.id, path="xyz"))

    def test_inputs4job_with_correct_path(self):
        # The exposure inputs are returned.
        inp1 = models.Input(owner=self.job.owner, path=self.paths.next(),
                            input_type="exposure", size=self.sizes.next())
        inp1.save()
        models.Input2job(oq_job=self.job, input=inp1).save()
        path = self.paths.next()
        inp2 = models.Input(owner=self.job.owner, path=path,
                            input_type="rupture", size=self.sizes.next())
        inp2.save()
        models.Input2job(oq_job=self.job, input=inp2).save()
        self.assertEqual([inp2], models.inputs4job(self.job.id, path=path))

    def test_inputs4job_with_correct_input_type_and_path(self):
        # The source inputs are returned.
        inp1 = models.Input(owner=self.job.owner, path=self.paths.next(),
                            input_type="source", size=self.sizes.next())
        inp1.save()
        models.Input2job(oq_job=self.job, input=inp1).save()
        path = self.paths.next()
        inp2 = models.Input(owner=self.job.owner, path=path,
                            input_type="source", size=self.sizes.next())
        inp2.save()
        models.Input2job(oq_job=self.job, input=inp2).save()
        inp3 = models.Input(owner=self.job.owner, path=self.paths.next(),
                            input_type="source", size=self.sizes.next())
        inp3.save()
        models.Input2job(oq_job=self.job, input=inp3).save()
        self.assertEqual(
            [inp2],
            models.inputs4job(self.job.id, input_type="source", path=path))


class Inputs4HazCalcTestCase(unittest.TestCase):

    def test_no_inputs(self):
        self.assertEqual([], models.inputs4haz_calc(-1))

    def test_a_few_inputs(self):
        cfg = helpers.demo_file('simple_fault_demo_hazard/job.ini')
        params, files = engine2.parse_config(open(cfg, 'r'), force_inputs=True)
        owner = helpers.default_user()
        hc = engine2.create_hazard_calculation(owner, params, files.values())

        expected_ids = sorted([x.id for x in files.values()])

        inputs = models.inputs4haz_calc(hc.id)

        actual_ids = sorted([x.id for x in inputs])

        self.assertEqual(expected_ids, actual_ids)

    def test_with_input_type(self):
        cfg = helpers.demo_file('simple_fault_demo_hazard/job.ini')
        params, files = engine2.parse_config(open(cfg, 'r'), force_inputs=True)
        owner = helpers.default_user()
        hc = engine2.create_hazard_calculation(owner, params, files.values())

        # It should only be 1 id, actually.
        expected_ids = [x.id for x in files.values()
                        if x.input_type == 'lt_source']

        inputs = models.inputs4haz_calc(hc.id, input_type='lt_source')

        actual_ids = sorted([x.id for x in inputs])

        self.assertEqual(expected_ids, actual_ids)


class HazardCalculationGeometryTestCase(unittest.TestCase):
    """Test special geometry handling in the HazardCalculation constructor."""

    def test_sites_from_wkt(self):
        # should succeed with no errors
        hjp = models.HazardCalculation(sites='MULTIPOINT(1 2, 3 4)')
        expected_wkt = (
            'MULTIPOINT (1.0000000000000000 2.0000000000000000,'
            ' 3.0000000000000000 4.0000000000000000)'
        )

        self.assertEqual(expected_wkt, hjp.sites.wkt)

    def test_sites_invalid_str(self):
        self.assertRaises(ValueError, models.HazardCalculation, sites='a 5')

    def test_sites_odd_num_of_coords_in_str_list(self):
        self.assertRaises(ValueError, models.HazardCalculation, sites='1 2, 3')

    def test_sites_valid_str_list(self):
        hjp = models.HazardCalculation(sites='1 2, 3 4')
        expected_wkt = (
            'MULTIPOINT (1.0000000000000000 2.0000000000000000,'
            ' 3.0000000000000000 4.0000000000000000)'
        )

        self.assertEqual(expected_wkt, hjp.sites.wkt)

    def test_region_from_wkt(self):
        hjp = models.HazardCalculation(region='POLYGON((1 2, 3 4, 5 6, 1 2))')
        expected_wkt = (
            'POLYGON ((1.0000000000000000 2.0000000000000000, '
            '3.0000000000000000 4.0000000000000000, '
            '5.0000000000000000 6.0000000000000000, '
            '1.0000000000000000 2.0000000000000000))'
        )

        self.assertEqual(expected_wkt, hjp.region.wkt)

    def test_region_invalid_str(self):
        self.assertRaises(
            ValueError, models.HazardCalculation,
            region='0, 0, 5a 5, 1, 3, 0, 0'
        )

    def test_region_odd_num_of_coords_in_str_list(self):
        self.assertRaises(
            ValueError, models.HazardCalculation, region='1 2, 3 4, 5 6, 1'
        )

    def test_region_valid_str_list(self):
        # note that the last coord (with closes the ring) can be ommitted
        # in this case
        hjp = models.HazardCalculation(region='1 2, 3 4, 5 6')
        expected_wkt = (
            'POLYGON ((1.0000000000000000 2.0000000000000000, '
            '3.0000000000000000 4.0000000000000000, '
            '5.0000000000000000 6.0000000000000000, '
            '1.0000000000000000 2.0000000000000000))'
        )

        self.assertEqual(expected_wkt, hjp.region.wkt)
