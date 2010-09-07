# vim: tabstop=4 shiftwidth=4 softtabstop=4
"""
Collection of base classes for processing 
spatially-related data."""

import math
from ordereddict import *

import geohash
from shapely import geometry
from shapely import wkt

from opengem import flags
FLAGS = flags.FLAGS

flags.DEFINE_integer('distance_precision', 12, 
    "Points within this geohash precision will be considered the same point")

LineString = geometry.LineString
Point = geometry.Point


class Region(object):
    """A container of polygons, used for bounds checking"""
    def __init__(self, polygon):
        self._grid = None
        self.polygon = polygon
        self.cell_size = 0.1
        # TODO(JMC): Make this a multipolygon instead?

    @classmethod
    def from_coordinates(cls, coordinates):
        """Build a region from a set of coordinates"""
        polygon = geometry.Polygon(coordinates)
        return cls(polygon)
    
    @classmethod
    def from_simple(cls, top_left, bottom_right):
        """Build a region from two corners (top left, bottom right)"""
        points = [top_left,
                  (top_left[0], bottom_right[1]),
                  bottom_right,
                  (bottom_right[0], top_left[1])]
        return cls.from_coordinates(points)
    
    @classmethod
    def from_file(cls, path):
        """Load a region from a wkt file with a single polygon"""
        with open(path) as wkt_file:
            polygon = wkt.loads(wkt_file.read())
            return cls(polygon=polygon)
    
    @property
    def bounds(self):
        """Returns a bounding box containing the whole region"""
        return self.polygon.bounds
    
    @property
    def lower_left_corner(self):
        """Lower left corner of the containing bounding box"""
        (minx, miny, _maxx, _maxy) = self.bounds
        return Site(miny, minx)
        
    @property
    def lower_right_corner(self):
        """Lower right corner of the containing bounding box"""
        (_minx, miny, maxx, _maxy) = self.bounds
        return Site(miny, maxx)
            
    @property
    def upper_left_corner(self):
        """Upper left corner of the containing bounding box"""
        (minx, _miny, _maxx, maxy) = self.bounds
        return Site(maxy, minx)
        
    @property
    def upper_right_corner(self):
        """Upper right corner of the containing bounding box"""
        (_minx, _miny, maxx, maxy) = self.bounds
        return Site(maxy, maxx)
    
    @property
    def grid(self):
        """Returns a proxy interface that maps lat/lon 
        to col/row based on a specific cellsize. Proxy is
        also iterable."""
        if not self._grid:
            if not self.cell_size:
                raise Exception("Can't generate grid without cell_size being set")
            self._grid = Grid(self, self.cell_size)
        return self._grid
    
    def __iter__(self):    
        if not self.cell_size:
            raise Exception("Can't generate grid without cell_size being set")
        for gridpoint in self.grid:
            yield gridpoint.site


class RegionConstraint(Region):
    """Extends a basic region to work as a constraint on parsers"""
    def match(self, point):
        """Point (specified by Point class or tuple) is contained?"""
        if isinstance(point, Site):
            point = point.point
        if not isinstance(point, geometry.Point): 
            point = geometry.Point(point[0], point[1])
        test = self.polygon.contains(point) or self.polygon.touches(point)
        # print "Does point match? %s" % (test)
        return test


class GridPoint(object):
    """Simple (trivial) point class"""
    def __init__(self, grid, column, row):
        self.column = column
        self.row = row
        self.grid = grid
    
    def __eq__(self, other):
        if isinstance(other, Site):
            other = self.grid.point_at(other)
        test = (self.__hash__() == other.__hash__())
        # print "Do gridpoints match? %s" % test
        return test
    
    @property
    def site(self):
        return self.grid.site_at(self)

    def hash(self):
        return self.__hash__()
        
    def __repr__(self):
        return str(self.__hash__())

    def __hash__(self):
        return self.column * 1000000000 + self.row 
        #, int(self.grid.cell_size)

    def __str__(self):
        return self.__repr__()


class Grid(object):
    """Grid is a proxy interface to Region, which translates
    lat/lon to col/row"""
    
    def __init__(self, region, cell_size):
        self.region = region
        self.cell_size = cell_size
        self.lower_left_corner = self.region.lower_left_corner
        self.columns = self._longitude_to_column(
                    self.region.upper_right_corner.longitude)
        self.rows = self._latitude_to_row(
                    self.region.upper_right_corner.latitude)
        print "Grid with %s rows and %s columns" % (self.rows, self.columns)

    def check_site(self, site):
        """Confirm that the site is contained by the region"""
        return self.check_point(site.point)
    
    def check_point(self, point):    
        # print "Checking point at %s" % point
        if (self.region.polygon.contains(point)):
            return True
        if self.region.polygon.touches(point):
            return True
        raise Exception("Point is not on the Grid")
    
    def check_gridpoint(self, gridpoint):
        """Confirm that the point is contained by the region"""
        point = Point(self._column_to_longitude(gridpoint.column),
                             self._row_to_latitude(gridpoint.row))
        return self.check_point(point)
    
    def _latitude_to_row(self, latitude):
        """Calculate row from latitude value"""
        latitude_offset = math.fabs(latitude - self.lower_left_corner.latitude)
        # print "lat offset = %s" % latitude_offset
        return int((latitude_offset / self.cell_size)) + 1

    def _row_to_latitude(self, row):
        return self.lower_left_corner.latitude + ((row-1) * self.cell_size)

    def _longitude_to_column(self, longitude):
        """Calculate column from longitude value"""
        longitude_offset = longitude - self.lower_left_corner.longitude
        # print "long offset = %s" % longitude_offset
        return int((longitude_offset / self.cell_size) + 1)
    
    def _column_to_longitude(self, column):
        return self.lower_left_corner.longitude + ((column-1) * self.cell_size)

    def point_at(self, site):
        """Translates a site into a matrix bidimensional point."""
        self.check_site(site)
        row = self._latitude_to_row(site.latitude)
        column = self._longitude_to_column(site.longitude)
        return GridPoint(self, column, row)
    
    def site_at(self, gridpoint):    
        return Site(self._column_to_longitude(gridpoint.column),
                             self._row_to_latitude(gridpoint.row))
    def __iter__(self):
        # print "Iterating my grid, with a total of %s rows and %s columns" % (self.rows, self.columns)
        for row in range(1, self.rows):
            for col in range(1, self.columns):
                try:
                    point = GridPoint(self, col, row)
                    self.check_gridpoint(point)
                    yield point
                except Exception, e:
                    pass

def c_mul(a, b):
    return eval(hex((long(a) * b) & 0xFFFFFFFFL)[:-1])

class Site(object):
    """Site is a dictionary-keyable point"""
    
    def __init__(self, longitude, latitude):
        self.point = geometry.Point(longitude, latitude)
    
    @property
    def longitude(self):
        "Point x value is longitude"
        return self.point.x
        
    @property
    def latitude(self):
        "Point y value is latitude"
        return self.point.y

    def __eq__(self, other):
        return self.hash() == other.hash()
    
    def equals(self, other):
        return self.point.equals(other)
    
    def hash(self):
        return self._geohash()
    
    def __hash__(self):
        if not self:
            return 0 # empty
        hash = self._geohash()
        value = ord(hash[0]) << 7
        for char in hash:
            value = c_mul(1000003, value) ^ ord(char)
        value = value ^ len(hash)
        if value == -1:
            value = -2
        return value
    
    def _geohash(self):
        """A geohash-encoded string for dict keys"""
        return geohash.encode(self.point.y, self.point.x, 
            precision=FLAGS.distance_precision)
    
    def __cmp__(self, other):
        return self._geohash() == other._geohash()
    
    def __repr__(self):
        return self._geohash()
        
    def __str__(self):
        return "<Site(%s, %s)>" % (self.longitude, self.latitude)


class Curve(object):
    """This class defines a curve (discrete function)
    used in the risk domain."""

    def __init__(self, values):
        # if values is a bare dict, we'll have problems...
        if not isinstance(values, OrderedDict):
            raise Exception("You need to use an OrderedDict here.")
        self.values = values

    def __eq__(self, other):
        return self.values == other.values

    def __str__(self):
        return self.values.__str__()

    @property
    def domain(self):
        """Returns the domain values of this curve."""
        return self.values.keys()

    @property
    def codomain(self):
        """Returns the codomain values of this curve."""
        return self.values.values()

    def get_for(self, x_value):
        """Returns the y value (codomain) corresponding
        to the given x value (domain)."""
        return self.values[x_value]

EMPTY_CURVE = Curve(OrderedDict())

def FastCurve(values):
    odict = OrderedDict()
    for key, val in values:
        odict[key] = val
    return Curve(odict)