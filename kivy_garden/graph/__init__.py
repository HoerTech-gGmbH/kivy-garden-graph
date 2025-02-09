'''
Graph
======

The :class:`Graph` widget is a widget for displaying plots. It supports
drawing multiple plot with different colors on the Graph. It also supports
axes titles, ticks, labeled ticks, grids and a log or linear representation on
both the x and y axis, independently.

To display a plot. First create a graph which will function as a "canvas" for
the plots. Then create plot objects e.g. MeshLinePlot and add them to the
graph.

To create a graph with x-axis between 0-100, y-axis between -1 to 1, x and y
labels of and X and Y, respectively, x major and minor ticks every 25, 5 units,
respectively, y major ticks every 1 units, full x and y grids and with
a red line plot containing a sin wave on this range::

    from kivy_garden.graph import Graph, MeshLinePlot
    graph = Graph(xlabel='X', ylabel='Y', x_ticks_minor=5,
                  x_ticks_major=25, y_ticks_major=1,
                  y_grid_label=True, x_grid_label=True, padding=5,
                  x_grid=True, y_grid=True, xmin=-0, xmax=100, ymin=-1, ymax=1)
    plot = MeshLinePlot(color=[1, 0, 0, 1])
    plot.points = [(x, sin(x / 10.)) for x in range(0, 101)]
    graph.add_plot(plot)

The MeshLinePlot plot is a particular plot which draws a set of points using
a mesh object. The points are given as a list of tuples, with each tuple
being a (x, y) coordinate in the graph's units.

You can create different types of plots other than MeshLinePlot by inheriting
from the Plot class and implementing the required functions. The Graph object
provides a "canvas" to which a Plot's instructions are added. The plot object
is responsible for updating these instructions to show within the bounding
box of the graph the proper plot. The Graph notifies the Plot when it needs
to be redrawn due to changes. See the MeshLinePlot class for how it is done.

The current availables plots are:

    * `MeshStemPlot`
    * `MeshLinePlot`
    * `SmoothLinePlot` - require Kivy 1.8.1

.. note::

    The graph uses a stencil view to clip the plots to the graph display area.
    As with the stencil graphics instructions, you cannot stack more than 8
    stencil-aware widgets.

'''

__all__ = ('Graph', 'Plot', 'MeshLinePlot', 'MeshStemPlot', 'LinePlot',
           'SmoothLinePlot', 'ContourPlot', 'ScatterPlot', 'PointPlot',
           'LineAndMarkerPlot')

from typing import Optional, List, Tuple, Any, Callable, Union

from kivy.graphics.instructions import InstructionGroup, Instruction
from kivy.graphics.vertex_instructions import Line, SmoothLine, Ellipse
from kivy.metrics import dp, sp
from kivy.uix.widget import Widget
from kivy.uix.label import Label
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.stencilview import StencilView
from kivy.properties import NumericProperty, BooleanProperty, \
    BoundedNumericProperty, StringProperty, ListProperty, ObjectProperty, \
    DictProperty, AliasProperty, ReferenceListProperty, ColorProperty, \
    OptionProperty
from kivy.clock import Clock
from kivy.graphics import Mesh, Color, Rectangle, Point
from kivy.graphics import Fbo
from kivy.graphics.texture import Texture
from kivy.event import EventDispatcher
from kivy.lang import Builder
from kivy.logger import Logger
from kivy import metrics
from math import log10, floor, ceil, sqrt
from decimal import Decimal
from itertools import chain
try:
    import numpy as np
except ImportError as e:
    np = None

from ._version import __version__


def identity(x):
    return x


def exp10(x):
    return 10 ** x


Builder.load_string("""
<GraphRotatedLabel>:
    canvas.before:
        PushMatrix
        Rotate:
            angle: root.angle
            axis: 0, 0, 1
            origin: root.center
    canvas.after:
        PopMatrix
""")


class GraphRotatedLabel(Label):
    angle = NumericProperty(0)


class Axis(EventDispatcher):
    pass


class XAxis(Axis):
    pass


class YAxis(Axis):
    pass


Builder.load_string("""
<GraphLegend>:
    orientation: "vertical"
    pos_hint: {"top": 1, "right": 1}
    size: self.minimum_size
    spacing: self.parent.padding if self.parent else 0
    padding: (self.parent.padding * 2 + self.marker_width, \
        self.parent.padding, self.parent.padding, self.parent.padding) \
        if self.parent else (0, 0, 0, 0)
    canvas.before:
        Color:
            rgba: self.parent.background_color if self.parent else (0, 0, 0, 0)
        Rectangle:
            size: self.size
            pos: self.pos
        Color:
            rgba: self.parent.border_color if self.parent else (0, 0, 0, 0)
        Line:
            rectangle: self.pos + self.size
""")


class GraphLegend(BoxLayout):
    """The Legend of a Graph.

    Set the legend's pos_hint property to position it relative to the graph's
    plotting area. Here, the graph's padding property is taken into account. So, for example
    a value of {'top': 1, 'right': 1} (the default) will position the legend in the
    top right corner inside the plotting area with a distance set by the graph's padding
    property's value to the plotting area's edges.
    Note: The position of the window has no influence to the graph's size.
        Meaning, setting the legend's pos_hint property to {'x': 1, 'center_y': .5}
        will position the legend vertically centered to the right of the plotting
        area. But this will probably be outside of the graph widget's area, so the
        legend might lie outside of the screen or under another widget.

    Example:

        >>> legend = []
        >>> graph = Graph(xmin=0, xmax=10, ymin=-1, ymax=1)
        >>> plot = LinePlot(color=[1, 0, 0, 1])
        >>> plot.points = [(x / 10, sin(x / 10)) for x in range(-0, 101)]
        >>> graph.add_plot(plot)
        >>> legend.append(('sine', plot))
        >>> plot = LinePlot(color=[0, 1, 0, 1])
        >>> plot.points = [(x / 10, cos(x / 10)) for x in range(-0, 101)]
        >>> graph.add_plot(plot)
        >>> legend.append(('cosine', plot))
        >>> graph.legend = legend
        >>> graph.legend.pos_hint = {'top': 1, 'center_x': .5}
    """

    marker_width = BoundedNumericProperty(dp(20), min=0)
    """Maximum width of the markers in the legend.
    
    Each marker displayed in the legend is of the same size as the plot's markers,
    but with this value as a maximum width. For line plots, this will be the length of the
    line displayed in the legend.
    
    Negative values are not allowed. 
    
    :data:`marker_width` is a :class:`kivy.properties.BoundedNumericProperty`,
    defaults to 20 dp.
    """

    marker_height = BoundedNumericProperty(dp(12), min=0)
    """Maximum height of the markers in the legend.
    
    Each marker displayed in the legend is of the same size as the plot's markers,
    but with this value as a maximum height.
    
    Negative values are not allowed.
    
    :data:`marker_height` is a :class:`kivy.properties.BoundedNumericProperty`,
    defaults to 12 dp.
    """

    marker_size = ReferenceListProperty(marker_width, marker_height)
    """Maximum size of the markers in the legend.
    
    :data:`marker_size` is a :class:`kivy.properties.ReferenceListProperty` of
    (:data:`marker_width`, :data:`marker_height`) properties.
    """


class Graph(Widget):
    '''Graph class, see module documentation for more information.
    '''

    # triggers a full reload of graphics
    _trigger = ObjectProperty(None)
    # triggers only a repositioning of objects due to size/pos updates
    _trigger_size = ObjectProperty(None)
    # triggers only a update of colors, e.g. tick_color
    _trigger_color = ObjectProperty(None)
    # holds widget with the x-axis label
    _xlabel = ObjectProperty(None, allownone=True)
    # holds widget with the y-axis label
    _ylabel = ObjectProperty(None, allownone=True)
    # holds all the x-axis tick mark labels
    _x_grid_label = ListProperty([])
    # holds all the y-axis tick mark labels
    _y_grid_label = ListProperty([])
    # the mesh drawing all the ticks/grids
    _mesh_ticks = ObjectProperty(None)
    # the mesh which draws the surrounding rectangle
    _mesh_rect = ObjectProperty(None)
    # a list of locations of major and minor ticks. The values are not
    # but is in the axis min - max range
    _ticks_majorx = ListProperty([])
    _ticks_minorx = ListProperty([])
    _ticks_majory = ListProperty([])
    _ticks_minory = ListProperty([])

    tick_color = ListProperty([.25, .25, .25, 1])
    '''Color of the grid/ticks, default to 1/4. grey.
    '''

    background_color = ListProperty([0, 0, 0, 0])
    '''Color of the background, defaults to transparent
    '''

    border_color = ListProperty([1, 1, 1, 1])
    '''Color of the border, defaults to white
    '''

    label_options = DictProperty()
    '''Label options that will be passed to `:class:`kivy.uix.Label`.
    
    These options are applied to axis labels, tick labels and legend labels,
    if not overwritten by :data:`tick_label_options` or :data:`legend_label_options`
    respectively.
    
    :data:`label_options` is an :class:`kivy.properties.DictProperty`
    and defaults to the empty dict.
    '''

    tick_label_options = DictProperty()
    '''Additional label options for the tick labels.
    
    These options are applied to tick labels and do overwrite the values in
    :data:`label_options` for the tick labels.
    
    :data:`tick_label_options` is an :class:`kivy.properties.DictProperty`
    and defaults to the empty dict.
    '''

    legend_label_options = DictProperty()
    '''Additional label options for the legend labels.
    
    These options are applied to legend labels and do overwrite the values in
    :data:`label_options` for the legend labels.
    
    :data:`legend_label_options` is an :class:`kivy.properties.DictProperty`
    and defaults to the empty dict.
    '''

    def _get_legend(self):
        return self._legend

    def _set_legend(self, legend: Union[Tuple[str, Any], None]):
        if legend and self._legend:
            while self._legend.children:
                self._legend.remove_widget(self.legend.children[0])
        elif legend:
            self._legend = GraphLegend()
            self._legend.bind(pos=self._trigger_legend, size=self._trigger_legend, pos_hint=self._trigger_legend,
                              marker_size=self._trigger_legend)
            self.add_widget(self._legend)
        elif self._legend:
            self.remove_widget(self._legend)
            self._legend = None
            self._legend_plots = []
            return True
        else:
            return False
        self._legend_plots = []
        self._legend.canvas.clear()
        for name, plot in legend:
            options = self.label_options.copy()
            options.update(**self.legend_label_options)
            label = Label(text=name, **options, size_hint=(None, None))
            def set_size(instance, size):
                instance.size = size
            label.bind(texture_size=set_size)
            drawings = plot.create_legend_drawings()
            for drawing in drawings:
                self._legend.canvas.add(drawing)
            self._legend_plots.append(plot)
            self._legend.add_widget(label)
        return True

    legend: Union[List[Tuple[str, Any]], GraphLegend] = AliasProperty(_get_legend, _set_legend)
    """Legend of graph's plots.
    
    You set the legend with an iterable yielding tuples containing the name
    and :class:`Plot` instance, you want to be displayed.
    Getting the legend returns an instance of :class:`GraphLegend`.
    
    See the :class:`GraphLegend` class documentation for a usage example.
    
    :data:`legend` is a :class:`~kivy.properties.AliasProperty`,
    defaults to None.
    """

    _with_stencilbuffer = BooleanProperty(True)
    '''Whether :class:`Graph`'s FBO should use FrameBuffer (True) or not
    (False).

    .. warning:: This property is internal and so should be used with care.
    It can break some other graphic instructions used by the :class:`Graph`,
    for example you can have problems when drawing :class:`SmoothLinePlot`
    plots, so use it only when you know what exactly you are doing.

    :data:`_with_stencilbuffer` is a :class:`~kivy.properties.BooleanProperty`,
    defaults to True.
    '''

    def __init__(self, **kwargs):
        self._legend: Optional[GraphLegend] = None
        self._legend_plots: Tuple[Plot, ...] = tuple()
        super(Graph, self).__init__(**kwargs)

        with self.canvas:
            self._fbo = Fbo(
                size=self.size, with_stencilbuffer=self._with_stencilbuffer)

        with self._fbo:
            self._background_color = Color(*self.background_color)
            self._background_rect = Rectangle(size=self.size)
            self._mesh_ticks_color = Color(*self.tick_color)
            self._mesh_ticks = Mesh(mode='lines')
            self._mesh_rect_color = Color(*self.border_color)
            self._mesh_rect = Mesh(mode='line_strip')

        with self.canvas:
            Color(1, 1, 1)
            self._fbo_rect = Rectangle(
                size=self.size, texture=self._fbo.texture)

        mesh = self._mesh_rect
        mesh.vertices = [0] * (5 * 4)
        mesh.indices = range(5)

        self._plot_area = StencilView()
        self.add_widget(self._plot_area)

        t = self._trigger = Clock.create_trigger(self._redraw_all)
        ts = self._trigger_size = Clock.create_trigger(self._redraw_size)
        tc = self._trigger_color = Clock.create_trigger(self._update_colors)
        tl = self._trigger_legend = Clock.create_trigger(self._update_legend)

        self.bind(center=ts, padding=ts, precision=ts, plots=ts, x_grid=ts,
                  y_grid=ts, draw_border=ts)
        self.bind(xmin=t, xmax=t, xlog=t, x_ticks_major=t, x_ticks_minor=t,
                  xlabel=t, x_grid_label=t, ymin=t, ymax=t, ylog=t,
                  y_ticks_major=t, y_ticks_minor=t, ylabel=t, y_grid_label=t,
                  label_options=t, x_ticks_angle=t,
                  tick_label_options=t, legend_label_options=t)
        self.bind(tick_color=tc, background_color=tc, border_color=tc)
        self.bind(legend=tl, view_pos=tl, view_size=tl, pos=tl)
        self._trigger()

    def add_widget(self, widget):
        if widget is self._plot_area:
            canvas = self.canvas
            self.canvas = self._fbo
        super(Graph, self).add_widget(widget)
        if widget is self._plot_area:
            self.canvas = canvas

    def remove_widget(self, widget):
        if widget is self._plot_area:
            canvas = self.canvas
            self.canvas = self._fbo
        super(Graph, self).remove_widget(widget)
        if widget is self._plot_area:
            self.canvas = canvas

    def _get_ticks(self, major, minor, log, s_min, s_max):
        if isinstance(major, (list, tuple)) != isinstance(minor, (list, tuple)):
            minor = type(major)()
        points_major = []
        points_minor = []
        if isinstance(major, (list, tuple)):
            points_major = [p for p in major if s_min <= p <= s_max or s_min >= p >= s_max]
            points_minor = [p for p in minor if (s_min <= p <= s_max or s_min >= p >= s_max) and p not in points_major]
            if log:
                points_major = [log10(p) for p in points_major]
                points_minor = [log10(p) for p in points_minor]
        elif major > 0:
            minor = max(minor, 0)
            if log and s_max > s_min:
                s_min = log10(s_min)
                s_max = log10(s_max)
                # count the decades in min - max. This is in actual decades,
                # not logs.
                n_decades = floor(s_max - s_min)
                # for the fractional part of the last decade, we need to
                # convert the log value, x, to 10**x but need to handle
                # differently if the last incomplete decade has a decade
                # boundary in it
                if floor(s_min + n_decades) != floor(s_max):
                    n_decades += 1 - (10 ** (s_min + n_decades + 1) - 10 **
                                      s_max) / 10 ** floor(s_max + 1)
                else:
                    n_decades += ((10 ** s_max - 10 ** (s_min + n_decades)) /
                                  10 ** floor(s_max + 1))
                # this might be larger than what is needed, but we delete
                # excess later
                n_ticks_major = n_decades / float(major)
                n_ticks = int(floor(n_ticks_major * (minor if minor >=
                                                     1. else 1.0))) + 2
                # in decade multiples, e.g. 0.1 of the decade, the distance
                # between ticks
                decade_dist = major / float(minor if minor else 1.0)

                points_minor = [0] * n_ticks
                points_major = [0] * n_ticks
                k = 0  # position in points major
                k2 = 0  # position in points minor
                # because each decade is missing 0.1 of the decade, if a tick
                # falls in < min_pos skip it
                min_pos = 0.1 - 0.00001 * decade_dist
                s_min_low = floor(s_min)
                # first real tick location. value is in fractions of decades
                # from the start we have to use decimals here, otherwise
                # floating point inaccuracies results in bad values
                start_dec = ceil((10 ** Decimal(s_min - s_min_low - 1)) /
                                 Decimal(decade_dist)) * decade_dist
                count_min = (0 if not minor else
                             floor(start_dec / decade_dist) % minor)
                start_dec += s_min_low
                count = 0  # number of ticks we currently have passed start
                while True:
                    # this is the current position in decade that we are.
                    # e.g. -0.9 means that we're at 0.1 of the 10**ceil(-0.9)
                    # decade
                    pos_dec = start_dec + decade_dist * count
                    pos_dec_low = floor(pos_dec)
                    diff = pos_dec - pos_dec_low
                    zero = abs(diff) < 0.001 * decade_dist
                    if zero:
                        # the same value as pos_dec but in log scale
                        pos_log = pos_dec_low
                    else:
                        pos_log = log10((pos_dec - pos_dec_low
                                         ) * 10 ** ceil(pos_dec))
                    if pos_log > s_max:
                        break
                    count += 1
                    if zero or diff >= min_pos:
                        if minor and not count_min % minor:
                            points_major[k] = pos_log
                            k += 1
                        else:
                            points_minor[k2] = pos_log
                            k2 += 1
                    count_min += 1
            elif not log and s_max != s_min:
                # distance between each tick
                tick_dist = major / float(minor if minor else 1.0)
                n_ticks = int(floor(abs((s_max - s_min) / tick_dist)) + 1)
                tick_dist = abs(tick_dist) * (1 if s_min < s_max else -1)
                points_major = [0] * int(floor(abs((s_max - s_min) / float(major)))
                                         + 1)
                points_minor = [0] * (n_ticks - len(points_major) + 1)
                k = 0  # position in points major
                k2 = 0  # position in points minor
                for m in range(0, n_ticks):
                    if minor and m % minor:
                        points_minor[k2] = m * tick_dist + s_min
                        k2 += 1
                    else:
                        points_major[k] = m * tick_dist + s_min
                        k += 1
            else:
                k = k2 = 1
            del points_major[k:]
            del points_minor[k2:]
        return sorted(points_major, reverse=s_min > s_max),\
               sorted(points_minor, reverse=s_min > s_max)

    def _update_labels(self):
        xlabel = self._xlabel
        ylabel = self._ylabel
        x = self.x
        y = self.y
        width = self.width
        height = self.height
        padding = self.padding
        x_next = padding + x
        y_next = padding + y
        xextent = width + x
        yextent = height + y
        ymin = self.ymin
        ymax = self.ymax
        xmin = self.xmin
        precision = self.precision
        x_overlap = False
        y_overlap = False
        # set up x and y axis labels
        if xlabel:
            xlabel.text = self.xlabel
            xlabel.texture_update()
            xlabel.size = xlabel.texture_size
            xlabel.pos = int(
                x + width / 2. - xlabel.width / 2.), int(padding + y)
            y_next += padding + xlabel.height
        if ylabel:
            ylabel.text = self.ylabel
            ylabel.texture_update()
            ylabel.size = ylabel.texture_size
            ylabel.x = padding + x - (ylabel.width / 2. - ylabel.height / 2.)
            x_next += padding + ylabel.height
        xpoints = self._ticks_majorx
        xlabels = self._x_grid_label
        xlabel_grid = self.x_grid_label
        ylabel_grid = self.y_grid_label
        ypoints = self._ticks_majory
        ylabels = self._y_grid_label
        # now x and y tick mark labels
        if len(ylabels) and ylabel_grid:
            # horizontal size of the largest tick label, to have enough room
            funcexp = exp10 if self.ylog else identity
            funclog = log10 if self.ylog else identity
            get_text = \
                (lambda _k: self.y_grid_label(funcexp(ypoints[_k]))) if isinstance(self.y_grid_label, Callable) else \
                self.y_grid_label.__getitem__ if isinstance(self.y_grid_label, (tuple, list, str)) else \
                lambda _k: precision % funcexp(ypoints[_k])
            ylabels[0].text = get_text(0)
            ylabels[0].texture_update()
            y1 = ylabels[0].texture_size
            y_start = y_next + (padding + y1[1] if len(xlabels) and xlabel_grid
                                else 0) + \
                               (padding + y1[1] if not y_next else 0)
            yextent = y + height - padding - y1[1] / 2.

            ymin = funclog(ymin)
            ratio = (yextent - y_start) / float(funclog(ymax) - ymin)
            y_start -= y1[1] / 2.
            y1 = y1[0]
            for k in range(len(ylabels)):
                try:
                    ylabels[k].text = get_text(k)
                except IndexError:
                    break
                ylabels[k].texture_update()
                ylabels[k].size = ylabels[k].texture_size
                y1 = max(y1, ylabels[k].texture_size[0])
            for k in range(len(ylabels)):
                ylabels[k].pos = (
                    int(x_next) - ylabels[k].width + y1,
                    int(y_start + (ypoints[k] - ymin) * ratio))
            if len(ylabels) > 1 and ylabels[0].top > ylabels[1].y:
                y_overlap = True
            else:
                x_next += y1 + padding
        if len(xlabels) and xlabel_grid:
            funcexp = exp10 if self.xlog else identity
            funclog = log10 if self.xlog else identity
            get_text = \
                (lambda _k: self.x_grid_label(funcexp(xpoints[_k]))) if isinstance(self.x_grid_label, Callable) else \
                self.x_grid_label.__getitem__ if isinstance(self.x_grid_label, (tuple, list, str)) else \
                lambda _k: precision % funcexp(xpoints[_k])
            # find the distance from the end that'll fit the last tick label
            xlabels[0].text = get_text(-1)
            xlabels[0].texture_update()
            xextent = x + width - xlabels[0].texture_size[0] / 2. - padding
            # find the distance from the start that'll fit the first tick label
            if not x_next:
                xlabels[0].text = get_text(0)
                xlabels[0].texture_update()
                x_next = padding + xlabels[0].texture_size[0] / 2.
            xmin = funclog(xmin)
            ratio = (xextent - x_next) / float(funclog(self.xmax) - xmin)
            right = -1
            for k in range(len(xlabels)):
                try:
                    xlabels[k].text = get_text(k)
                except IndexError:
                    pass
                # update the size so we can center the labels on ticks
                xlabels[k].texture_update()
                xlabels[k].size = xlabels[k].texture_size
                half_ts = xlabels[k].texture_size[0] / 2.
                xlabels[k].pos = (
                    int(x_next + (xpoints[k] - xmin) * ratio - half_ts),
                    int(y_next))
                if xlabels[k].x < right:
                    x_overlap = True
                    break
                right = xlabels[k].right
            if not x_overlap:
                y_next += padding + xlabels[0].texture_size[1]
        # now re-center the x and y axis labels
        if xlabel:
            xlabel.x = int(
                x_next + (xextent - x_next) / 2. - xlabel.width / 2.)
        if ylabel:
            ylabel.y = int(
                y_next + (yextent - y_next) / 2. - ylabel.height / 2.)
            ylabel.angle = 90
        if x_overlap:
            for k in range(len(xlabels)):
                xlabels[k].text = ''
        if y_overlap:
            for k in range(len(ylabels)):
                ylabels[k].text = ''
        return x_next - x, y_next - y, xextent - x, yextent - y

    def _update_ticks(self, size):
        # re-compute the positions of the bounding rectangle
        mesh = self._mesh_rect
        vert = mesh.vertices
        if self.draw_border:
            s0, s1, s2, s3 = size
            vert[0] = s0
            vert[1] = s1
            vert[4] = s2
            vert[5] = s1
            vert[8] = s2
            vert[9] = s3
            vert[12] = s0
            vert[13] = s3
            vert[16] = s0
            vert[17] = s1
        else:
            vert[0:18] = [0 for k in range(18)]
        mesh.vertices = vert
        # re-compute the positions of the x/y axis ticks
        mesh = self._mesh_ticks
        vert = mesh.vertices
        start = 0
        xpoints = self._ticks_majorx
        ypoints = self._ticks_majory
        xpoints2 = self._ticks_minorx
        ypoints2 = self._ticks_minory
        ylog = self.ylog
        xlog = self.xlog
        xmin = self.xmin
        xmax = self.xmax
        if xlog:
            xmin = log10(xmin)
            xmax = log10(xmax)
        ymin = self.ymin
        ymax = self.ymax
        if ylog:
            ymin = log10(ymin)
            ymax = log10(ymax)
        if len(xpoints):
            top = size[3] if self.x_grid else metrics.dp(12) + size[1]
            ratio = (size[2] - size[0]) / float(xmax - xmin)
            for k in range(start, len(xpoints) + start):
                vert[k * 8] = size[0] + (xpoints[k - start] - xmin) * ratio
                vert[k * 8 + 1] = size[1]
                vert[k * 8 + 4] = vert[k * 8]
                vert[k * 8 + 5] = top
            start += len(xpoints)
        if len(xpoints2):
            top = metrics.dp(8) + size[1]
            ratio = (size[2] - size[0]) / float(xmax - xmin)
            for k in range(start, len(xpoints2) + start):
                vert[k * 8] = size[0] + (xpoints2[k - start] - xmin) * ratio
                vert[k * 8 + 1] = size[1]
                vert[k * 8 + 4] = vert[k * 8]
                vert[k * 8 + 5] = top
            start += len(xpoints2)
        if len(ypoints):
            top = size[2] if self.y_grid else metrics.dp(12) + size[0]
            ratio = (size[3] - size[1]) / float(ymax - ymin)
            for k in range(start, len(ypoints) + start):
                vert[k * 8 + 1] = size[1] + (ypoints[k - start] - ymin) * ratio
                vert[k * 8 + 5] = vert[k * 8 + 1]
                vert[k * 8] = size[0]
                vert[k * 8 + 4] = top
            start += len(ypoints)
        if len(ypoints2):
            top = metrics.dp(8) + size[0]
            ratio = (size[3] - size[1]) / float(ymax - ymin)
            for k in range(start, len(ypoints2) + start):
                vert[k * 8 + 1] = size[1] + (
                    ypoints2[k - start] - ymin) * ratio
                vert[k * 8 + 5] = vert[k * 8 + 1]
                vert[k * 8] = size[0]
                vert[k * 8 + 4] = top
        mesh.vertices = vert

    x_axis = ListProperty([None])
    y_axis = ListProperty([None])

    def get_x_axis(self, axis=0):
        if axis == 0:
            return self.xlog, self.xmin, self.xmax
        info = self.x_axis[axis]
        return info["log"], info["min"], info["max"]

    def get_y_axis(self, axis=0):
        if axis == 0:
            return self.ylog, self.ymin, self.ymax
        info = self.y_axis[axis]
        return info["log"], info["min"], info["max"]

    def add_x_axis(self, xmin, xmax, xlog=False):
        data = {
            "log": xlog,
            "min": xmin,
            "max": xmax
        }
        self.x_axis.append(data)
        return data

    def add_y_axis(self, ymin, ymax, ylog=False):
        data = {
            "log": ylog,
            "min": ymin,
            "max": ymax
        }
        self.y_axis.append(data)
        return data

    def _update_plots(self, size):
        for plot in self.plots:
            xlog, xmin, xmax = self.get_x_axis(plot.x_axis)
            ylog, ymin, ymax = self.get_y_axis(plot.y_axis)
            plot._update(xlog, xmin, xmax, ylog, ymin, ymax, size)

    def _update_colors(self, *args):
        self._mesh_ticks_color.rgba = tuple(self.tick_color)
        self._background_color.rgba = tuple(self.background_color)
        self._mesh_rect_color.rgba = tuple(self.border_color)

    def _redraw_all(self, *args):
        # add/remove all the required labels
        xpoints_major, xpoints_minor = self._redraw_x(*args)
        ypoints_major, ypoints_minor = self._redraw_y(*args)

        if self._legend:
            options = self.label_options.copy()
            options.update(**self.legend_label_options)
            for c in self._legend.children:
                for k, v in options.items():
                    setattr(c, k, v)

        mesh = self._mesh_ticks
        n_points = (len(xpoints_major) + len(xpoints_minor) +
                    len(ypoints_major) + len(ypoints_minor))
        mesh.vertices = [0] * (n_points * 8)
        mesh.indices = [k for k in range(n_points * 2)]
        self._redraw_size()

    def _redraw_x(self, *args):
        if self.xlabel:
            xlabel = self._xlabel
            if not xlabel:
                xlabel = Label()
                self.add_widget(xlabel)
                self._xlabel = xlabel

            for k, v in self.label_options.items():
                setattr(xlabel, k, v)

        else:
            xlabel = self._xlabel
            if xlabel:
                self.remove_widget(xlabel)
                self._xlabel = None
        grids = self._x_grid_label
        xpoints_major, xpoints_minor = self._get_ticks(self.x_ticks_major,
                                                       self.x_ticks_minor,
                                                       self.xlog, self.xmin,
                                                       self.xmax)
        self._ticks_majorx = xpoints_major
        self._ticks_minorx = xpoints_minor

        if not self.x_grid_label:
            n_labels = 0
        elif isinstance(self.x_grid_label, (tuple, list, str)):
            n_labels = min(len(xpoints_major), len(self.x_grid_label))
        else:
            n_labels = len(xpoints_major)

        for k in range(n_labels, len(grids)):
            self.remove_widget(grids[k])
        del grids[n_labels:]

        grid_len = len(grids)
        grids.extend([None] * (n_labels - len(grids)))
        options = self.label_options.copy()
        options.update(**self.tick_label_options)
        for k in range(grid_len, n_labels):
            grids[k] = GraphRotatedLabel(
                angle=self.x_ticks_angle,
                **options)
            self.add_widget(grids[k])
        return xpoints_major, xpoints_minor

    def _redraw_y(self, *args):
        if self.ylabel:
            ylabel = self._ylabel
            if not ylabel:
                ylabel = GraphRotatedLabel()
                self.add_widget(ylabel)
                self._ylabel = ylabel

            for k, v in self.label_options.items():
                setattr(ylabel, k, v)
        else:
            ylabel = self._ylabel
            if ylabel:
                self.remove_widget(ylabel)
                self._ylabel = None
        grids = self._y_grid_label
        ypoints_major, ypoints_minor = self._get_ticks(self.y_ticks_major,
                                                       self.y_ticks_minor,
                                                       self.ylog, self.ymin,
                                                       self.ymax)
        self._ticks_majory = ypoints_major
        self._ticks_minory = ypoints_minor

        if not self.y_grid_label:
            n_labels = 0
        elif isinstance(self.y_grid_label, (tuple, list, str)):
            n_labels = min(len(ypoints_major), len(self.y_grid_label))
        else:
            n_labels = len(ypoints_major)

        for k in range(n_labels, len(grids)):
            self.remove_widget(grids[k])
        del grids[n_labels:]

        grid_len = len(grids)
        grids.extend([None] * (n_labels - len(grids)))
        options = self.label_options.copy()
        options.update(**self.tick_label_options)
        for k in range(grid_len, n_labels):
            grids[k] = Label(**options)
            self.add_widget(grids[k])
        return ypoints_major, ypoints_minor

    def _redraw_size(self, *args):
        # size a 4-tuple describing the bounding box in which we can draw
        # graphs, it's (x0, y0, x1, y1), which correspond with the bottom left
        # and top right corner locations, respectively
        self._clear_buffer()
        size = self._update_labels()
        self.view_pos = self._plot_area.pos = (size[0], size[1])
        self.view_size = self._plot_area.size = (
            size[2] - size[0], size[3] - size[1])

        if self.size[0] and self.size[1]:
            self._fbo.size = self.size
        else:
            self._fbo.size = 1, 1  # gl errors otherwise
        self._fbo_rect.texture = self._fbo.texture
        self._fbo_rect.size = self.size
        self._fbo_rect.pos = self.pos
        self._background_rect.size = self.size
        self._update_ticks(size)
        self._update_plots(size)

    def _update_legend(self, *_):
        if self.legend:
            self.legend.size = self.legend.minimum_size
            pos, size = self.view_pos, self.view_size
            ph = self.legend.pos_hint
            if 'x' in ph or 'center_x' in ph or 'right' in ph:
                x = size[0] * (ph.get('x', ph.get('center_x', ph.get('right')))) \
                    - (self.legend.width * (0 if 'x' in ph else .5 if 'center_x' in ph else 1)) \
                    - (self.padding * (-1 if 'x' in ph else 0 if 'center_x' in ph else 1))
                self.legend.x = self.x + pos[0] + x
            if 'y' in ph or 'center_y' in ph or 'top' in ph:
                y = size[1] * (ph.get('y', ph.get('center_y', ph.get('top')))) \
                    - (self.legend.height * (0 if 'y' in ph else .5 if 'center_y' in ph else 1)) \
                    - (self.padding * (-1 if 'y' in ph else 0 if 'center_y' in ph else 1))
                self.legend.y = self.y + pos[1] + y
            for i, plot in enumerate(self._legend_plots):
                label = self.legend.children[-(i+1)]
                drawing_center = label.x - self.legend.spacing - self.legend.marker_width / 2, label.center_y
                plot.draw_legend(drawing_center, self.legend.marker_size)

    def _clear_buffer(self, *largs):
        fbo = self._fbo
        fbo.bind()
        fbo.clear_buffer()
        fbo.release()

    def add_plot(self, plot):
        '''Add a new plot to this graph.

        :Parameters:
            `plot`:
                Plot to add to this graph.

        >>> graph = Graph()
        >>> plot = MeshLinePlot(mode='line_strip', color=[1, 0, 0, 1])
        >>> plot.points = [(x / 10., sin(x / 50.)) for x in range(-0, 101)]
        >>> graph.add_plot(plot)
        '''
        if plot in self.plots:
            return
        add = self._plot_area.canvas.add
        for instr in plot.get_drawings():
            add(instr)
        plot.bind(on_clear_plot=self._clear_buffer)
        self.plots.append(plot)

    def remove_plot(self, plot):
        '''Remove a plot from this graph.

        :Parameters:
            `plot`:
                Plot to remove from this graph.

        >>> graph = Graph()
        >>> plot = MeshLinePlot(mode='line_strip', color=[1, 0, 0, 1])
        >>> plot.points = [(x / 10., sin(x / 50.)) for x in range(-0, 101)]
        >>> graph.add_plot(plot)
        >>> graph.remove_plot(plot)
        '''
        if plot not in self.plots:
            return
        remove = self._plot_area.canvas.remove
        for instr in plot.get_drawings():
            remove(instr)
        plot.unbind(on_clear_plot=self._clear_buffer)
        self.plots.remove(plot)
        self._clear_buffer()

    def collide_plot(self, x, y):
        '''Determine if the given coordinates fall inside the plot area. Use
        `x, y = self.to_widget(x, y, relative=True)` to first convert into
        widget coordinates if it's in window coordinates because it's assumed
        to be given in local widget coordinates, relative to the graph's pos.

        :Parameters:
            `x, y`:
                The coordinates to test.
        '''
        adj_x, adj_y = x - self._plot_area.pos[0], y - self._plot_area.pos[1]
        return 0 <= adj_x <= self._plot_area.size[0] \
            and 0 <= adj_y <= self._plot_area.size[1]

    def to_data(self, x, y):
        '''Convert widget coords to data coords. Use
        `x, y = self.to_widget(x, y, relative=True)` to first convert into
        widget coordinates if it's in window coordinates because it's assumed
        to be given in local widget coordinates, relative to the graph's pos.

        :Parameters:
            `x, y`:
                The coordinates to convert.

        If the graph has multiple axes, use :class:`Plot.unproject` instead.
        '''
        adj_x = float(x - self._plot_area.pos[0])
        adj_y = float(y - self._plot_area.pos[1])
        norm_x = adj_x / self._plot_area.size[0]
        norm_y = adj_y / self._plot_area.size[1]
        if self.xlog:
            xmin, xmax = log10(self.xmin), log10(self.xmax)
            conv_x = 10.**(norm_x * (xmax - xmin) + xmin)
        else:
            conv_x = norm_x * (self.xmax - self.xmin) + self.xmin
        if self.ylog:
            ymin, ymax = log10(self.ymin), log10(self.ymax)
            conv_y = 10.**(norm_y * (ymax - ymin) + ymin)
        else:
            conv_y = norm_y * (self.ymax - self.ymin) + self.ymin
        return [conv_x, conv_y]

    xmin = NumericProperty(0.)
    '''The x-axis minimum value.

    If :data:`xlog` is True, xmin must be larger than zero.
    If :data:`xmax` < :data:`xmin`, the x axis will be displayed reversed.

    :data:`xmin` is a :class:`~kivy.properties.NumericProperty`, defaults to 0.
    '''

    xmax = NumericProperty(100.)
    '''The x-axis maximum value.
    
    If :data:`xmax` < :data:`xmin`, the x axis will be displayed reversed.

    :data:`xmax` is a :class:`~kivy.properties.NumericProperty`, defaults to 0.
    '''

    xlog = BooleanProperty(False)
    '''Determines whether the x-axis should be displayed logarithmically (True)
    or linearly (False).

    :data:`xlog` is a :class:`~kivy.properties.BooleanProperty`, defaults
    to False.
    '''

    x_ticks_major = ObjectProperty(0)
    '''Positioning of major tick marks on the x-axis.

    May either be a numerical value indicating the distance between ticks
    or a list or tuple giving the absolute tick positions.

    If :data:`x_ticks_major` is a numeric value greater than zero, it
    determines the distance between the major tick marks. Major tick marks
    start from min and re-occur at every ticks_major until :data:`xmax`.
    If :data:`xmax` doesn't overlap with a integer multiple of ticks_major,
    no tick will occur at :data:`xmax`. Values below or equal to zero
    indicate no tick marks.

    If :data:`xlog` is true, then this indicates the distance between ticks
    in multiples of current decade. E.g. if :data:`xmin` is 0.1 and
    ticks_major is 0.1, it means there will be a tick at every 10th of the
    decade, i.e. 0.1 ... 0.9, 1, 2... If it is 0.3, the ticks will occur at
    0.1, 0.3, 0.6, 0.9, 2, 5, 8, 10. You'll notice that it went from 8 to 10
    instead of to 20, that's so that we can say 0.5 and have ticks at every
    half decade, e.g. 0.1, 0.5, 1, 5, 10, 50... Similarly, if ticks_major is
    1.5, there will be ticks at 0.1, 5, 100, 5,000... Also notice, that there's
    always a major tick at the start. Finally, if e.g. :data:`xmin` is 0.6
    and this 0.5 there will be ticks at 0.6, 1, 5...
    
    If :data:`x_ticks_major` is a list or tuple, a major tick will be displayed
    at each of the given values, if it is in the range of :data:`xmin` to :data:`xmax`.

    :data:`x_ticks_major` is a
    :class:`~kivy.properties.ObjectProperty`, defaults to 0.
    '''

    x_ticks_minor = ObjectProperty(0)
    '''Positioning of minor tick marks on the x-axis.

    May either be a numerical value indicating the number of subintervals
    between major ticks or a list or tuple giving the absolute tick positions.
    If either one of :data:`x_ticks_minor` and :data:`x_ticks_major` is a
    numerical value and the other one is not, :data:`x_ticks_minor` is ignored.
    
    If :data:`x_ticks_major` is a numerical value greater than zero, it
    determines the number of sub-intervals into which ticks_major is divided.
    The actual number of minor ticks between the major ticks is
    ticks_minor - 1. Only used if ticks_major is non-zero. If there's no major
    tick at xmax then the number of minor ticks after the last major
    tick will be however many ticks fit until xmax.

    If self.xlog is true, then this indicates the number of intervals the
    distance between major ticks is divided. The result is the number of
    multiples of decades between ticks. I.e. if ticks_minor is 10, then if
    ticks_major is 1, there will be ticks at 0.1, 0.2...0.9, 1, 2, 3... If
    ticks_major is 0.3, ticks will occur at 0.1, 0.12, 0.15, 0.18... Finally,
    as is common, if ticks major is 1, and ticks minor is 5, there will be
    ticks at 0.1, 0.2, 0.4... 0.8, 1, 2...
    
    If :data:`x_ticks_minor` is a list or tuple, a minor tick will be displayed
    at each of the given values, if it is in the range of :data:`xmin` to :data:`xmax`.

    :data:`x_ticks_minor` is a
    :class:`~kivy.properties.ObjectProperty`, defaults to 0.
    '''

    x_grid = BooleanProperty(False)
    '''Determines whether the x-axis has tick marks or a full grid.

    If :data:`x_ticks_major` is non-zero, then if x_grid is False tick marks
    will be displayed at every major tick. If x_grid is True, instead of ticks,
    a vertical line will be displayed at every major tick.

    :data:`x_grid` is a :class:`~kivy.properties.BooleanProperty`, defaults
    to False.
    '''

    x_grid_label: Union[bool, Callable[[float], str], List[str], Tuple[str, ...], str] \
        = ObjectProperty(False)
    '''Whether and how labels should be displayed beneath each major tick.
    
    If false, no tick labels are shown.
    If true, each major tick will have a label containing the axis value displayed at precision :data:`precision`.
    It can also be a callable returning the string representation for a given float value.
    It can also be a list or tuple of strings or a string itself. In that case the k-th item will be displayed at the
    k-th major label.

    :data:`x_grid_label` is a :class:`~kivy.properties.ObjectProperty`,
    defaults to False.
    '''

    xlabel = StringProperty('')
    '''The label for the x-axis. If not empty it is displayed in the center of
    the axis.

    :data:`xlabel` is a :class:`~kivy.properties.StringProperty`,
    defaults to ''.
    '''

    ymin = NumericProperty(0.)
    '''The y-axis minimum value.

    If :data:`ylog` is True, ymin must be larger than zero.
    If :data:`ymax` < :data:`ymin`, the y axis will be displayed reversed.

    :data:`ymin` is a :class:`~kivy.properties.NumericProperty`, defaults to 0.
    '''

    ymax = NumericProperty(100.)
    '''The y-axis maximum value.
    
    If :data:`ymax` < :data:`ymin`, the y axis will be displayed reversed.

    :data:`ymax` is a :class:`~kivy.properties.NumericProperty`, defaults to 0.
    '''

    ylog = BooleanProperty(False)
    '''Determines whether the y-axis should be displayed logarithmically (True)
    or linearly (False).

    :data:`ylog` is a :class:`~kivy.properties.BooleanProperty`, defaults
    to False.
    '''

    y_ticks_major = ObjectProperty(0)
    '''Positioning of major tick marks on the y-axis.
    See :data:`x_ticks_major`.

    :data:`y_ticks_major` is a
    :class:`~kivy.properties.ObjectProperty`, defaults to 0.
    '''

    y_ticks_minor = ObjectProperty(0)
    '''Positioning of minor tick marks on the y-axis.
    See :data:`x_ticks_minor`.

    :data:`y_ticks_minor` is a
    :class:`~kivy.properties.ObjectProperty`, defaults to 0.
    '''

    y_grid = BooleanProperty(False)
    '''Determines whether the y-axis has tick marks or a full grid. See
    :data:`x_grid`.

    :data:`y_grid` is a :class:`~kivy.properties.BooleanProperty`, defaults
    to False.
    '''

    y_grid_label: Union[bool, Callable[[float], str], List[str], Tuple[str, ...], str] \
        = ObjectProperty(False)
    '''Whether and how labels should be displayed beneath each major tick.
    
    If false, no tick labels are shown.
    If true, each major tick will have a label containing the axis value displayed at precision :data:`precision`.
    It can also be a callable returning the string representation for a given float value.
    It can also be a list or tuple of strings or a string itself. In that case the k-th item will be displayed at the
    k-th major label.

    :data:`y_grid_label` is a :class:`~kivy.properties.ObjectProperty`,
    defaults to False.
    '''

    ylabel = StringProperty('')
    '''The label for the y-axis. If not empty it is displayed in the center of
    the axis.

    :data:`ylabel` is a :class:`~kivy.properties.StringProperty`,
    defaults to ''.
    '''

    padding = NumericProperty('5dp')
    '''Padding distances between the labels, axes titles and graph, as
    well between the widget and the objects near the boundaries.

    :data:`padding` is a :class:`~kivy.properties.NumericProperty`, defaults
    to 5dp.
    '''

    x_ticks_angle = NumericProperty(0)
    '''Rotate angle of the x-axis tick marks.

    :data:`x_ticks_angle` is a :class:`~kivy.properties.NumericProperty`,
    defaults to 0.
    '''

    precision = StringProperty('%g')
    '''Determines the numerical precision of the tick mark labels. This value
    governs how the numbers are converted into string representation. Accepted
    values are those listed in Python's manual in the
    "String Formatting Operations" section.

    :data:`precision` is a :class:`~kivy.properties.StringProperty`, defaults
    to '%g'.
    '''

    draw_border = BooleanProperty(True)
    '''Whether a border is drawn around the canvas of the graph where the
    plots are displayed.

    :data:`draw_border` is a :class:`~kivy.properties.BooleanProperty`,
    defaults to True.
    '''

    plots = ListProperty([])
    '''Holds a list of all the plots in the graph. To add and remove plots
    from the graph use :data:`add_plot` and :data:`add_plot`. Do not add
    directly edit this list.

    :data:`plots` is a :class:`~kivy.properties.ListProperty`,
    defaults to [].
    '''

    view_size = ObjectProperty((0, 0))
    '''The size of the graph viewing area - the area where the plots are
    displayed, excluding labels etc.
    '''

    view_pos = ObjectProperty((0, 0))
    '''The pos of the graph viewing area - the area where the plots are
    displayed, excluding labels etc. It is relative to the graph's pos.
    '''


class Plot(EventDispatcher):
    '''Plot class, see module documentation for more information.

    :Events:
        `on_clear_plot`
            Fired before a plot updates the display and lets the fbo know that
            it should clear the old drawings.

    ..versionadded:: 0.4
    '''

    __events__ = ('on_clear_plot', )

    # most recent values of the params used to draw the plot
    params = DictProperty({'xlog': False, 'xmin': 0, 'xmax': 100,
                           'ylog': False, 'ymin': 0, 'ymax': 100,
                           'size': (0, 0, 0, 0)})

    color = ColorProperty([1, 1, 1, 1])
    '''Color of the plot.
    '''

    points = ListProperty([])
    '''List of (x, y) points to be displayed in the plot.

    The elements of points are 2-tuples, (x, y). The points are displayed
    based on the mode setting.

    :data:`points` is a :class:`~kivy.properties.ListProperty`, defaults to
    [].
    '''

    x_axis = NumericProperty(0)
    '''Index of the X axis to use, defaults to 0
    '''

    y_axis = NumericProperty(0)
    '''Index of the Y axis to use, defaults to 0
    '''

    def __init__(self, **kwargs):
        super(Plot, self).__init__(**kwargs)
        self.ask_draw = Clock.create_trigger(self.draw)
        self.bind(params=self.ask_draw, points=self.ask_draw)
        self._drawings = self.create_drawings()

    def funcx(self):
        """Return a function that convert or not the X value according to plot
        prameters"""
        return log10 if self.params["xlog"] else lambda x: x

    def funcy(self):
        """Return a function that convert or not the Y value according to plot
        prameters"""
        return log10 if self.params["ylog"] else lambda y: y

    def x_px(self):
        """Return a function that convert the X value of the graph to the
        pixel coordinate on the plot, according to the plot settings and axis
        settings. It's relative to the graph pos.
        """
        funcx = self.funcx()
        params = self.params
        size = params["size"]
        xmin = funcx(params["xmin"])
        xmax = funcx(params["xmax"])
        xrange = float(xmax - xmin)
        ratiox = 0
        if xrange:
            ratiox = (size[2] - size[0]) / xrange

        return lambda x: (funcx(x) - xmin) * ratiox + size[0]

    def y_px(self):
        """Return a function that convert the Y value of the graph to the
        pixel coordinate on the plot, according to the plot settings and axis
        settings. The returned value is relative to the graph pos.
        """
        funcy = self.funcy()
        params = self.params
        size = params["size"]
        ymin = funcy(params["ymin"])
        ymax = funcy(params["ymax"])
        yrange = float(ymax - ymin)
        ratioy = 0
        if yrange:
            ratioy = (size[3] - size[1]) / yrange

        return lambda y: (funcy(y) - ymin) * ratioy + size[1]

    def unproject(self, x, y):
        """Return a function that unproject a pixel to a X/Y value on the plot
        (works only for linear, not log yet). `x`, `y`, is relative to the
        graph pos, so the graph's pos needs to be subtracted from x, y before
        passing it in.
        """
        params = self.params
        size = params["size"]

        xmin = params["xmin"]
        xmax = params["xmax"]
        xrange = float(xmax - xmin)
        ratiox = 0
        if xrange:
            ratiox = (size[2] - size[0]) / xrange

        ymin = params["ymin"]
        ymax = params["ymax"]
        yrange = float(ymax - ymin)
        ratioy = 0
        if yrange:
            ratioy = (size[3] - size[1]) / yrange

        x0 = (x - size[0]) / ratiox + xmin
        y0 = (y - size[1]) / ratioy + ymin
        return x0, y0

    def get_px_bounds(self):
        """Returns a dict containing the pixels bounds from the plot parameters.
         The returned values are relative to the graph pos.
        """
        params = self.params
        x_px = self.x_px()
        y_px = self.y_px()
        return {
            "xmin": x_px(params["xmin"]),
            "xmax": x_px(params["xmax"]),
            "ymin": y_px(params["ymin"]),
            "ymax": y_px(params["ymax"]),
        }

    def update(self, xlog, xmin, xmax, ylog, ymin, ymax, size):
        '''Called by graph whenever any of the parameters
        change. The plot should be recalculated then.
        log, min, max indicate the axis settings.
        size a 4-tuple describing the bounding box in which we can draw
        graphs, it's (x0, y0, x1, y1), which correspond with the bottom left
        and top right corner locations, respectively.
        '''
        self.params.update({
            'xlog': xlog, 'xmin': xmin, 'xmax': xmax, 'ylog': ylog,
            'ymin': ymin, 'ymax': ymax, 'size': size})

    def get_group(self):
        '''returns a string which is unique and is the group name given to all
        the instructions returned by _get_drawings. Graph uses this to remove
        these instructions when needed.
        '''
        return ''

    def get_drawings(self):
        '''returns a list of canvas instructions that will be added to the
        graph's canvas.
        '''
        if isinstance(self._drawings, (tuple, list)):
            return self._drawings
        return []

    def create_drawings(self):
        '''called once to create all the canvas instructions needed for the
        plot
        '''
        pass

    def create_legend_drawings(self):
        '''called when a legend is added containing this plot. return drawing instructions.
        '''
        return []

    def draw(self, *largs):
        '''draw the plot according to the params. It dispatches on_clear_plot
        so derived classes should call super before updating.
        '''
        self.dispatch('on_clear_plot')

    def draw_legend(self, center, maximum_size):
        '''draw the legend representation.
        '''
        pass

    def iterate_points(self):
        '''Iterate on all the points adjusted to the graph settings
        '''
        x_px = self.x_px()
        y_px = self.y_px()
        for x, y in self.points:
            yield x_px(x), y_px(y)

    def on_clear_plot(self, *largs):
        pass

    # compatibility layer
    _update = update
    _get_drawings = get_drawings
    _params = params


class MeshLinePlot(Plot):
    '''MeshLinePlot class which displays a set of points similar to a mesh.
    '''

    def _set_mode(self, value):
        if hasattr(self, '_mesh'):
            self._mesh.mode = value
        if hasattr(self, '_mesh_legend'):
            self._mesh_legend.mode = value
            self.draw_legend()

    mode = AliasProperty(lambda self: self._mesh.mode, _set_mode)
    '''VBO Mode used for drawing the points. Can be one of: 'points',
    'line_strip', 'line_loop', 'lines', 'triangle_strip', 'triangle_fan'.
    See :class:`~kivy.graphics.Mesh` for more details.

    Defaults to 'line_strip'.
    '''

    def create_drawings(self):
        self._color = Color(*self.color)
        self._mesh = Mesh(mode='line_strip')
        self.bind(
            color=lambda instr, value: setattr(self._color, "rgba", value))
        return [self._color, self._mesh]

    def create_legend_drawings(self):
        self._mesh_legend = Mesh(mode=self.mode)
        return [self._color, self._mesh_legend]

    def draw_legend(self, center=None, maximum_size=None):
        self._legend_center = center = center or self._legend_center
        self._legend_maximum_size = maximum_size = maximum_size or self._legend_maximum_size
        x, right = center[0] - .5 * maximum_size[0], center[0] + .5 * maximum_size[0]
        y, top = center[1] - .5 * maximum_size[1], center[1] + .5 * maximum_size[1]
        self._mesh_legend.vertices = \
            [x, center[1], 0, 0, right, center[1], 0, 0] if self.mode == 'line_strip' else \
            [x, y, 0, 0, x, top, 0, 0, right, top, 0, 0, right, y, 0, 0,
             center[0], center[1], 0, 0] if self.mode == "points" else \
            [x, y, 0, 0, center[0], top, 0, 0, center[0], y, 0, 0, right, top, 0, 0] if self.mode == "lines" else \
            [x, y, 0, 0, center[0], top, 0, 0, right, y, 0, 0]
        self._mesh_legend.indices = tuple(range(len(self._mesh_legend.vertices) // 4))

    def draw(self, *args):
        super(MeshLinePlot, self).draw(*args)
        self.plot_mesh()

    def plot_mesh(self):
        points = [p for p in self.iterate_points()]
        mesh, vert, _ = self.set_mesh_size(len(points))
        for k, (x, y) in enumerate(points):
            vert[k * 4] = x
            vert[k * 4 + 1] = y
        mesh.vertices = vert

    def set_mesh_size(self, size):
        mesh = self._mesh
        vert = mesh.vertices
        ind = mesh.indices
        diff = size - len(vert) // 4
        if diff < 0:
            del vert[4 * size:]
            del ind[size:]
        elif diff > 0:
            ind.extend(range(len(ind), len(ind) + diff))
            vert.extend([0] * (diff * 4))
        mesh.vertices = vert
        return mesh, vert, ind


class MeshStemPlot(MeshLinePlot):
    '''MeshStemPlot uses the MeshLinePlot class to draw a stem plot. The data
    provided is graphed from origin to the data point.
    '''

    def plot_mesh(self):
        points = [p for p in self.iterate_points()]
        mesh, vert, _ = self.set_mesh_size(len(points) * 2)
        y0 = self.y_px()(0)
        for k, (x, y) in enumerate(self.iterate_points()):
            vert[k * 8] = x
            vert[k * 8 + 1] = y0
            vert[k * 8 + 4] = x
            vert[k * 8 + 5] = y
        mesh.vertices = vert


class LinePlot(Plot):
    """LinePlot draws using a standard Line object.
    """

    line_width = NumericProperty(1)

    def create_drawings(self):
        from kivy.graphics import Line, RenderContext

        self._grc = RenderContext(
                use_parent_modelview=True,
                use_parent_projection=True)
        with self._grc:
            self._gcolor = Color(*self.color)
            self._gline = Line(
                points=[], cap='none',
                width=self.line_width, joint='round')

        return [self._grc]

    def draw(self, *args):
        super(LinePlot, self).draw(*args)
        # flatten the list
        points = []
        for x, y in self.iterate_points():
            points += [x, y]
        self._gline.points = points

    def create_legend_drawings(self):
        from kivy.graphics import Line, RenderContext

        self._grc_legend = RenderContext(
                use_parent_modelview=True,
                use_parent_projection=True)
        self._grc_legend.add(self._gcolor)
        with self._grc_legend:
            self._gline_legend = Line(
                points=[], cap='none', joint='round')
        return [self._grc_legend]

    def draw_legend(self, center, maximum_size):
        self._maximum_legend_line_width = maximum_size[1] / 2
        self._gline_legend.points = [center[0] - .5 * maximum_size[0], center[1],
                                     center[0] + .5 * maximum_size[0], center[1]]
        self._gline_legend.width = min(self.line_width, self._maximum_legend_line_width)

    def on_line_width(self, *largs):
        if hasattr(self, "_gline"):
            self._gline.width = self.line_width
        if hasattr(self, "_gline_legend"):
            self._gline_legend.width = min(self.line_width, self._maximum_legend_line_width)


class SmoothLinePlot(Plot):
    '''Smooth Plot class, see module documentation for more information.
    This plot use a specific Fragment shader for a custom anti aliasing.
    '''

    SMOOTH_FS = '''
    $HEADER$

    void main(void) {
        float edgewidth = 0.015625 * 64.;
        float t = texture2D(texture0, tex_coord0).r;
        float e = smoothstep(0., edgewidth, t);
        gl_FragColor = frag_color * vec4(1, 1, 1, e);
    }
    '''

    # XXX This gradient data is a 64x1 RGB image, and
    # values goes from 0 -> 255 -> 0.
    GRADIENT_DATA = (
        b"\x00\x00\x00\x07\x07\x07\x0f\x0f\x0f\x17\x17\x17\x1f\x1f\x1f"
        b"'''///777???GGGOOOWWW___gggooowww\x7f\x7f\x7f\x87\x87\x87"
        b"\x8f\x8f\x8f\x97\x97\x97\x9f\x9f\x9f\xa7\xa7\xa7\xaf\xaf\xaf"
        b"\xb7\xb7\xb7\xbf\xbf\xbf\xc7\xc7\xc7\xcf\xcf\xcf\xd7\xd7\xd7"
        b"\xdf\xdf\xdf\xe7\xe7\xe7\xef\xef\xef\xf7\xf7\xf7\xff\xff\xff"
        b"\xf6\xf6\xf6\xee\xee\xee\xe6\xe6\xe6\xde\xde\xde\xd5\xd5\xd5"
        b"\xcd\xcd\xcd\xc5\xc5\xc5\xbd\xbd\xbd\xb4\xb4\xb4\xac\xac\xac"
        b"\xa4\xa4\xa4\x9c\x9c\x9c\x94\x94\x94\x8b\x8b\x8b\x83\x83\x83"
        b"{{{sssjjjbbbZZZRRRJJJAAA999111)))   \x18\x18\x18\x10\x10\x10"
        b"\x08\x08\x08\x00\x00\x00")

    def create_drawings(self):
        from kivy.graphics import Line, RenderContext

        # very first time, create a texture for the shader
        if not hasattr(SmoothLinePlot, '_texture'):
            tex = Texture.create(size=(1, 64), colorfmt='rgb')
            tex.add_reload_observer(SmoothLinePlot._smooth_reload_observer)
            SmoothLinePlot._texture = tex
            SmoothLinePlot._smooth_reload_observer(tex)

        self._grc = RenderContext(
            fs=SmoothLinePlot.SMOOTH_FS,
            use_parent_modelview=True,
            use_parent_projection=True)
        with self._grc:
            self._gcolor = Color(*self.color)
            self._gline = Line(
                points=[], cap='none', width=2.,
                texture=SmoothLinePlot._texture)

        return [self._grc]

    @staticmethod
    def _smooth_reload_observer(texture):
        texture.blit_buffer(SmoothLinePlot.GRADIENT_DATA, colorfmt="rgb")

    def draw(self, *args):
        super(SmoothLinePlot, self).draw(*args)
        # flatten the list
        points = []
        for x, y in self.iterate_points():
            points += [x, y]
        self._gline.points = points

    def create_legend_drawings(self):
        return LinePlot.create_legend_drawings(self)

    def draw_legend(self, center, maximum_size):
        self.line_width = self._gline.width
        return LinePlot.draw_legend(self, center, maximum_size)


class ContourPlot(Plot):
    """
    ContourPlot visualizes 3 dimensional data as an intensity map image.
    The user must first specify 'xrange' and 'yrange' (tuples of min,max) and
    then 'data', the intensity values.
    `data`, is a MxN matrix, where the first dimension of size M specifies the
    `y` values, and the second dimension of size N specifies the `x` values.
    Axis Y and X values are assumed to be linearly spaced values from
    xrange/yrange and the dimensions of 'data', `MxN`, respectively.
    The color values are automatically scaled to the min and max z range of the
    data set.
    """
    _image = ObjectProperty(None)
    data = ObjectProperty(None, force_dispatch=True)
    xrange = ListProperty([0, 100])
    yrange = ListProperty([0, 100])

    def __init__(self, **kwargs):
        super(ContourPlot, self).__init__(**kwargs)
        self.bind(data=self.ask_draw, xrange=self.ask_draw,
                  yrange=self.ask_draw)

    def create_drawings(self):
        self._image = Rectangle()
        self._color = Color([1, 1, 1, 1])
        self.bind(
            color=lambda instr, value: setattr(self._color, 'rgba', value))
        return [self._color, self._image]

    def draw(self, *args):
        super(ContourPlot, self).draw(*args)
        data = self.data
        xdim, ydim = data.shape

        # Find the minimum and maximum z values
        zmax = data.max()
        zmin = data.min()
        rgb_scale_factor = 1.0 / (zmax - zmin) * 255
        # Scale the z values into RGB data
        buf = np.array(data, dtype=float, copy=True)
        np.subtract(buf, zmin, out=buf)
        np.multiply(buf, rgb_scale_factor, out=buf)
        # Duplicate into 3 dimensions (RGB) and convert to byte array
        buf = np.asarray(buf, dtype=np.uint8)
        buf = np.expand_dims(buf, axis=2)
        buf = np.concatenate((buf, buf, buf), axis=2)
        buf = np.reshape(buf, (xdim, ydim, 3))

        charbuf = bytearray(np.reshape(buf, (buf.size)))
        self._texture = Texture.create(size=(xdim, ydim), colorfmt='rgb')
        self._texture.blit_buffer(charbuf, colorfmt='rgb', bufferfmt='ubyte')
        image = self._image
        image.texture = self._texture

        x_px = self.x_px()
        y_px = self.y_px()
        bl = x_px(self.xrange[0]), y_px(self.yrange[0])
        tr = x_px(self.xrange[1]), y_px(self.yrange[1])
        image.pos = bl
        w = tr[0] - bl[0]
        h = tr[1] - bl[1]
        image.size = (w, h)


class BarPlot(Plot):
    '''BarPlot class which displays a bar graph.
    '''

    bar_width = NumericProperty(1)
    bar_spacing = NumericProperty(1.)
    graph = ObjectProperty(allownone=True)

    def __init__(self, *ar, **kw):
        super(BarPlot, self).__init__(*ar, **kw)
        self.bind(bar_width=self.ask_draw)
        self.bind(bar_width=lambda *_: self.draw_legend())
        self.bind(points=self.update_bar_width)
        self.bind(graph=self.update_bar_width)

    def update_bar_width(self, *ar):
        if not self.graph:
            return
        if len(self.points) < 2:
            return
        if self.graph.xmax == self.graph.xmin:
            return

        point_width = (
            len(self.points) *
            float(abs(self.graph.xmax) + abs(self.graph.xmin)) /
            float(abs(max(self.points)[0]) + abs(min(self.points)[0])))

        if not self.points:
            self.bar_width = 1
        else:
            self.bar_width = (
                (self.graph.width - self.graph.padding) /
                point_width * self.bar_spacing)

    def create_drawings(self):
        self._color = Color(*self.color)
        self._mesh = Mesh()
        self.bind(
            color=lambda instr, value: setattr(self._color, 'rgba', value))
        return [self._color, self._mesh]

    def create_legend_drawings(self):
        self._rectangle = Rectangle()
        return [self._color, self._rectangle]

    def draw_legend(self, center=None, maximum_size=None):
        if not hasattr(self, "_rectangle"):
            return
        self._legend_maximum_size = maximum_size = maximum_size or self._legend_maximum_size
        width = min(self.bar_width, maximum_size[0]) if self.bar_width >= 0 else maximum_size[0]
        height = maximum_size[1]
        if center:
            x = center[0] - width / 2
            y = center[1] - height / 2
        else:
            y = self._rectangle.pos[1]
            x = self._rectangle.pos[0] - width / 2 + self._rectangle.size[0] / 2
        self._rectangle.pos = x, y
        self._rectangle.size = width, height


    def draw(self, *args):
        super(BarPlot, self).draw(*args)
        points = self.points

        # The mesh only supports (2^16) - 1 indices, so...
        if len(points) * 6 > 65535:
            Logger.error(
                "BarPlot: cannot support more than 10922 points. "
                "Ignoring extra points.")
            points = points[:10922]

        point_len = len(points)
        mesh = self._mesh
        mesh.mode = 'triangles'
        vert = mesh.vertices
        ind = mesh.indices
        diff = len(points) * 6 - len(vert) // 4
        if diff < 0:
            del vert[24 * point_len:]
            del ind[point_len:]
        elif diff > 0:
            ind.extend(range(len(ind), len(ind) + diff))
            vert.extend([0] * (diff * 4))

        bounds = self.get_px_bounds()
        x_px = self.x_px()
        y_px = self.y_px()
        ymin = y_px(0)

        bar_width = self.bar_width
        if bar_width < 0:
            bar_width = x_px(bar_width) - bounds["xmin"]

        for k in range(point_len):
            p = points[k]
            x1 = x_px(p[0])
            x2 = x1 + bar_width
            y1 = ymin
            y2 = y_px(p[1])

            idx = k * 24
            # first triangle
            vert[idx] = x1
            vert[idx + 1] = y2
            vert[idx + 4] = x1
            vert[idx + 5] = y1
            vert[idx + 8] = x2
            vert[idx + 9] = y1
            # second triangle
            vert[idx + 12] = x1
            vert[idx + 13] = y2
            vert[idx + 16] = x2
            vert[idx + 17] = y2
            vert[idx + 20] = x2
            vert[idx + 21] = y1
        mesh.vertices = vert

    def _unbind_graph(self, graph):
        graph.unbind(width=self.update_bar_width,
                     xmin=self.update_bar_width,
                     ymin=self.update_bar_width)

    def bind_to_graph(self, graph):
        old_graph = self.graph

        if old_graph:
            # unbind from the old one
            self._unbind_graph(old_graph)

        # bind to the new one
        self.graph = graph
        graph.bind(width=self.update_bar_width,
                   xmin=self.update_bar_width,
                   ymin=self.update_bar_width)

    def unbind_from_graph(self):
        if self.graph:
            self._unbind_graph(self.graph)


class HBar(MeshLinePlot):
    '''HBar draw horizontal bar on all the Y points provided
    '''

    def plot_mesh(self, *args):
        points = self.points
        mesh, vert, ind = self.set_mesh_size(len(points) * 2)
        mesh.mode = "lines"

        bounds = self.get_px_bounds()
        px_xmin = bounds["xmin"]
        px_xmax = bounds["xmax"]
        y_px = self.y_px()
        for k, y in enumerate(points):
            y = y_px(y)
            vert[k * 8] = px_xmin
            vert[k * 8 + 1] = y
            vert[k * 8 + 4] = px_xmax
            vert[k * 8 + 5] = y
        mesh.vertices = vert


class VBar(MeshLinePlot):
    '''VBar draw vertical bar on all the X points provided
    '''

    def plot_mesh(self, *args):
        points = self.points
        mesh, vert, ind = self.set_mesh_size(len(points) * 2)
        mesh.mode = "lines"

        bounds = self.get_px_bounds()
        px_ymin = bounds["ymin"]
        px_ymax = bounds["ymax"]
        x_px = self.x_px()
        for k, x in enumerate(points):
            x = x_px(x)
            vert[k * 8] = x
            vert[k * 8 + 1] = px_ymin
            vert[k * 8 + 4] = x
            vert[k * 8 + 5] = px_ymax
        mesh.vertices = vert


class ScatterPlot(Plot):
    """
    ScatterPlot draws using a standard Point object.
    The pointsize can be controlled with :attr:`point_size`.

    >>> plot = ScatterPlot(color=[1, 0, 0, 1], point_size=5)
    """

    point_size = NumericProperty(1)
    """The point size of the scatter points. Defaults to 1.
    """

    def create_drawings(self):
        from kivy.graphics import Point, RenderContext

        self._points_context = RenderContext(
                use_parent_modelview=True,
                use_parent_projection=True)
        with self._points_context:
            self._gcolor = Color(*self.color)
            self._gpts = Point(points=[], pointsize=self.point_size)

        return [self._points_context]

    def create_legend_drawings(self):
        from kivy.graphics import Point, RenderContext

        self._points_legend_context = RenderContext(
                use_parent_modelview=True,
                use_parent_projection=True)
        self._points_legend_context.add(self._gcolor)
        with self._points_legend_context:
            self._gpts_legend = Point(points=[])

        return [self._points_legend_context]

    def draw(self, *args):
        super(ScatterPlot, self).draw(*args)
        # flatten the list
        self._gpts.points = list(chain(*self.iterate_points()))

    def draw_legend(self, center, maximum_size):
        self._maximum_legend_point_size = min(maximum_size) / 2
        self._gpts_legend.pointsize = min(self._maximum_legend_point_size, self.point_size)
        self._gpts_legend.points = center

    def on_point_size(self, *largs):
        if hasattr(self, "_gpts"):
            self._gpts.pointsize = self.point_size
        if hasattr(self, "_maximum_legend_point_size"):
            self._gpts_legend.pointsize = min(self.point_size, self._maximum_legend_point_size)


class PointPlot(Plot):
    '''Displays a set of points.
    '''

    point_size = NumericProperty(1)
    '''
    Defaults to 1.
    '''

    _color = None

    _point = None

    def __init__(self, **kwargs):
        super(PointPlot, self).__init__(**kwargs)

        def update_size(*largs):
            if self._point:
                self._point.pointsize = self.point_size
            if hasattr(self, "_maximum_legend_point_size"):
                self._point_legend.pointsize = min(self.point_size, self._maximum_legend_point_size)
        self.fbind('point_size', update_size)

        def update_color(*largs):
            if self._color:
                self._color.rgba = self.color
        self.fbind('color', update_color)

    def create_drawings(self):
        self._color = Color(*self.color)
        self._point = Point(pointsize=self.point_size)
        return [self._color, self._point]

    def create_legend_drawings(self):
        self._point_legend = Point()
        return [self._color, self._point_legend]

    def draw(self, *args):
        super(PointPlot, self).draw(*args)
        self._point.points = [v for p in self.iterate_points() for v in p]

    def draw_legend(self, center, maximum_size):
        self._maximum_legend_point_size = min(maximum_size) / 2
        self._point_legend.pointsize = min(self._maximum_legend_point_size, self.point_size)
        self._point_legend.points = center


class LineAndMarkerPlot(Plot):
    """A Plot consisting of a line and markers.

    The line is drawn using a :class:`kivy.graphics.SmoothLine` and can
    be adapted using the :data:`line_width` and :data:`color` properties.

    The markers can be adapted using the :data:`marker_shape`,
    :data:`marker_line_width`, :data:`marker_color` properties.
    """

    marker_shape: str = OptionProperty(None, allownone=True, options=[None, *'x+*-|<>v^osdOSD'])
    """The shape of the marker.
    
    The following values are allowed:
        None:   no marker
        'x':    cross
        '+':    plus sign
        '*':    asterisk
        '-':    horizontal line
        '|':    vertical line
        '<':    left-pointing open triangle
        '>':    right-pointing open triangle
        'v':    downward-pointing open triangle
        '^':    upward-pointing open triangle
        'o':    circle
        's':    square
        'd':    diamond
        'O':    filled circle
        'S':    filled square
        'D':    filled diamond
    
    :data:`marker_shape` is a :class:`kivy.properties.OptionProperty`
    and defaults to None.
    """

    marker_size: float = BoundedNumericProperty(dp(12), min=0)
    """Size of a single marker as the side length of a surrounding square.
    
    For markers, that are drawn as a line, e. g. 'o' or 's' markers, the actual
    outermost size will be :data:`marker_size` + 2 * :data:`marker_line_width`, because
    half the line will exceed the square defined by marker_size * marker_size.
    
    :data:`marker_size` is a :class:`kivy.properties.BoundedNumericProperty`
    with a minimum of 0 and defaults to 12 dp.
    """

    marker_line_width: float = BoundedNumericProperty(dp(1.5), min=0)
    """The line width with which the markers are drawn.
    
    For filled markers this value is ignored.
    
    :data:`marker_line_width` is a :class:`kivy.properties.BoundedNumericProperty`
    with a minimum of 0 and defaults to 1.5 dp.
    """

    line_width: float = BoundedNumericProperty(dp(1.1), min=0)
    """Line width of the line connecting the markers.
    
    :data:`line_width` is a :class:`kivy.properties.BoundedNumericProperty`
    with a minimum of 0 and defaults to 1.1 dp.
    """

    marker_color = ColorProperty(None, allownone=True)
    """Color of the markers.
    
    May be set to None, in which case the markers are drawn with the same
    color as the line, i. e. the color defines by :data:`color`.
    
    :data:`marker_color` is a :class:`kivy.properties.ColorProperty`
    and defaults to None.
    """

    legend_display = OptionProperty('marker', options=('marker', 'both', 'line'))
    """How to display this plot in the legend.
    
    Options:
        'marker':   Displays only the marker if :data:`marker_shape` is not None
                    and only the line otherwise.
        'both':     Displays line and marker.
        'line':     Displays only the line.
    
    :data:`legend_display` is a :class:`kivy.properties.OptionProperty`
    and defaults to 'marker'.
    """

    def __init__(self, **kwargs):

        # The following are set in self.create_drawings.
        self._color: Optional[Color] = None  # color drawing instruction
        self._marker_color: Optional[Color] = None  # marker_color drawing instruction
        self._line: Optional[Line] = None  # drawing instruction for the line connecting the markers
        # instruction group holding drawing instructions for the single markers
        self._marker_group: Optional[InstructionGroup] = None

        # instruction group holding drawing instructions for legend.
        self._legend_group: Optional[InstructionGroup] = None
        self._legend_line: Optional[Line] = None
        self._legend_marker: Optional[Instruction] = None
        # store legend marker center and max size
        self._legend_marker_center: Optional[Tuple[float, float]] = None
        self._legend_maximum_drawing_size: Optional[Tuple[float, float]] = None

        # list of drawing instructions for the plot markers
        self._markers: List[Instruction] = []

        # call super
        super().__init__(**kwargs)

        # In the following we do all the bindings so that the plot is always up to date.

        def update_marker_line_width(*_):
            for p in self._markers:
                if isinstance(p, Line):
                    p.width = self.marker_line_width
            if isinstance(self._legend_marker, Line):
                self._legend_marker.width = self.marker_line_width
        self.fbind('marker_line_width', update_marker_line_width)

        def update_line_width(*_):
            self._line.width = self.line_width
            if self._legend_line:
                self._legend_line.width = min(self.line_width, self._legend_maximum_drawing_size[1] / 2)
        self.fbind('line_width', update_line_width)

        # When the marker size changes, the endpoints of the marker lines change, so redraw.
        self.fbind('marker_size', lambda *_: self.draw_markers())
        self.fbind('marker_size', lambda *_: self.draw_legend())
        # When the shape of the markers changes, the Marker Line class may change, so create markers new and draw them.
        self.fbind('marker_shape', lambda *_: self.draw_markers(force_new=True))
        self.fbind('marker_shape', lambda *_: self.draw_legend(force_new=True))
        # Redraw legend, when legend_display changes.
        self.fbind('legend_display', lambda *_: self.draw_legend(force_new=True))

        def update_color(*_):
            if self._color:
                self._color.rgba = self.color
                self._marker_color.rgba = self.marker_color or self.color
        self.fbind('color', update_color)
        self.fbind('marker_color', update_color)

    def create_drawings(self):
        # superclass method
        self._color = Color(*self.color)
        self._line = SmoothLine(width=self.line_width)
        self._marker_color = Color(*(self.marker_color or self.color))
        self._marker_group = InstructionGroup()
        return [self._color, self._line, self._marker_color, self._marker_group]

    def draw(self, *_):
        # call superclass method
        super().draw()
        # Set the line's points.
        # They have to be simplified (see method's doc).
        # They need another format: [(x0, y0), (x1, y1), ...] -> [x0, y0, x1, y1, ...]
        self._line.points = [xy for p in self.simplify_points(list(self.iterate_points())) for xy in p]
        # Update all the markers of the plot.
        self.draw_markers()

    def get_marker(self):
        # This method returns a single marker.
        # We want to use SmoothLine in most cases,
        # but for some shapes we cannot use
        # simplify_points, since the line crosses itself.
        # So SmoothLine Does not work and we fall back to Line.
        shape = self.marker_shape
        if shape is None:
            return Instruction()
        if shape in 'x+*':
            return Line(width=self.marker_line_width)
        if shape in '-|<>v^sd':
            return Line(width=self.marker_line_width, joint='miter')
        if shape in 'o':
            return SmoothLine(width=self.marker_line_width, close=True, joint='round')
        if shape == 'O':
            return Ellipse()
        if shape == 'S':
            return Rectangle()
        if shape == 'D':
            return Mesh(indices=(0, 1, 2, 3), mode='triangle_fan')
        raise NotImplementedError()

    def draw_markers(self, force_new=False):

        super().draw()

        # Delete unneccessary markers.
        while len(self.points) < len(self._markers) or (force_new and self._markers):
            self._marker_group.remove(self._markers.pop())

        # While we have less markers than needed, instantiate new ones.
        while len(self.points) > len(self._markers):
            # Keep references in self._markers, to change their position and shape.
            self._markers.append(self.get_marker())
            # Each marker is a drawing instruction that needs to be added to the correct InstructionGroup
            # in order to be displayed.
            self._marker_group.add(self._markers[-1])

        for marker, point in zip(self._markers, self.iterate_points()):
            self.draw_marker(marker, self.marker_size, *point)

    @staticmethod
    def simplify_points(points: List[Tuple[float, float]]):
        """Delete points in a list that lie exactly on the line connecting it's two adjacent points.

        This is needed due to a bug in class´SmoothLine´.
        """
        points = points.copy()
        i = 0
        while len(points) > i + 2:
            if 1e-5 > abs((points[i + 1][1] - points[i][1]) / (points[i + 1][0] - points[i][0]) -
                          (points[i + 2][1] - points[i][1]) / (points[i + 2][0] - points[i][0])):
                points.pop(i + 1)
            else:
                i += 1
        return points

    def draw_marker(self, marker: Instruction, s, x, y):
        # Set the line's points according to the desired position of the marker.
        shape = self.marker_shape
        if shape is None:
            return
        x, cx, r = x - s / 2, x, x + s / 2
        y, cy, t = y - s / 2, y, y + s / 2
        d = .5 * sqrt(.5) * s
        if shape in 'x+*-|<>v^sd':
            marker.points = \
                (x, y, r, t, cx, cy, x, t, r, y) if shape == 'x' else \
                (x, cy, r, cy, cx, cy, cx, y, cx, t) if shape == '+' else \
                (x, cy, r, cy, cx, cy, cx, y, cx, t, cx, cy, cx - d, cy - d, cx + d, cy + d, cx, cy, cx - d, cy + d, cx + d, cy - d) \
                    if shape == '*' else \
                (x, cy, r, cy) if shape == '-' else \
                (cx, y, cx, t) if shape == '|' else \
                (x, y, r, cy, x, t) if shape == '>' else \
                (r, y, x, cy, r, t) if shape == '<' else \
                (x, t, cx, y, r, t) if shape == 'v' else \
                (x, y, cx, t, r, y) if shape == '^' else \
                (x, y, x, t, r, t, r, y, x, y, x, t) if shape == 's' else \
                (x, cy, cx, t, r, cy, cx, y, x, cy, cx, t) if shape == 'd' else \
                NotImplemented
        elif shape == 'o':
            marker.ellipse = (x, y, s, s)
        elif shape in 'OS':
            marker.pos = x, y
            marker.size = s, s
        elif shape == 'D':
            marker.vertices = (x, cy, 0, 0, cx, t, 0, 0, r, cy, 0, 0, cx, y, 0, 0)
        else:
            raise NotImplementedError()

    def create_legend_drawings(self):
        self._legend_line = SmoothLine(width=self.line_width)
        self._legend_marker = self.get_marker()
        self._legend_group = InstructionGroup()
        self._legend_group.add(self._color)
        self._legend_group.add(self._legend_line)
        self._legend_group.add(self._marker_color)
        self._legend_group.add(self._legend_marker)
        return [self._legend_group]

    def draw_legend(self, center=None, maximum_size=None, force_new=False):
        self._legend_maximum_drawing_size = maximum_size = maximum_size or self._legend_maximum_drawing_size
        self._legend_marker_center = center = center or self._legend_marker_center
        if not center:
            return
        if force_new:
            if self._legend_marker:
                self._legend_group.remove(self._legend_marker)
                self._legend_marker = None
            if not self.legend_display == 'line':
                self._legend_marker = self.get_marker()
                self._legend_group.add(self._legend_marker)
        if self._legend_marker:
            marker_size = min(self.marker_size, *maximum_size)
            self.draw_marker(self._legend_marker, marker_size, *center)
        self._legend_line.points = \
            [] if self.legend_display == 'marker' and self.marker_shape else \
            [center[0] - maximum_size[0] / 2, center[1],
             center[0] + maximum_size[0] / 2, center[1]]


if __name__ == '__main__':
    import itertools
    from math import sin, cos, pi
    from random import randrange
    from kivy.utils import get_color_from_hex as rgb
    from kivy.uix.boxlayout import BoxLayout
    from kivy.app import App

    class TestApp(App):

        def build(self):
            b = BoxLayout(orientation='vertical')
            # example of a custom theme
            colors = itertools.cycle([
                rgb('7dac9f'), rgb('dc7062'), rgb('66a8d4'), rgb('e5b060')])
            graph_theme = {
                'label_options': {
                    'color': rgb('444444'),  # color of tick labels and titles
                    'bold': True},
                'background_color': rgb('f8f8f2'),  # canvas background color
                'tick_color': rgb('808080'),  # ticks and grid
                'border_color': rgb('808080')}  # border drawn around each graph

            graph = Graph(
                xlabel='Cheese',
                ylabel='Apples',
                x_ticks_minor=5,
                x_ticks_major=25,
                y_ticks_major=1,
                y_grid_label=True,
                x_grid_label=True,
                padding=5,
                xlog=False,
                ylog=False,
                x_grid=True,
                y_grid=True,
                xmin=-50,
                xmax=50,
                ymin=-1,
                ymax=1,
                **graph_theme)

            plot = SmoothLinePlot(color=next(colors))
            plot.points = [(x / 10., sin(x / 50.)) for x in range(-500, 501)]
            # for efficiency, the x range matches xmin, xmax
            graph.add_plot(plot)

            plot = MeshLinePlot(color=next(colors))
            plot.points = [(x / 10., cos(x / 50.)) for x in range(-500, 501)]
            graph.add_plot(plot)
            self.plot = plot  # this is the moving graph, so keep a reference

            plot = MeshStemPlot(color=next(colors))
            graph.add_plot(plot)
            plot.points = [(x, x / 50.) for x in range(-50, 51)]

            plot = BarPlot(color=next(colors), bar_spacing=.72)
            graph.add_plot(plot)
            plot.bind_to_graph(graph)
            plot.points = [(x, .1 + randrange(10) / 10.) for x in range(-50, 1)]

            Clock.schedule_interval(self.update_points, 1 / 60.)

            graph2 = Graph(
                xlabel='Position (m)',
                ylabel='Time (s)',
                x_ticks_minor=0,
                x_ticks_major=1,
                y_ticks_major=10,
                y_grid_label=True,
                x_grid_label=True,
                padding=5,
                xlog=False,
                ylog=False,
                xmin=0,
                ymin=0,
                **graph_theme)
            b.add_widget(graph)

            if np is not None:
                (xbounds, ybounds, data) = self.make_contour_data()
                # This is required to fit the graph to the data extents
                graph2.xmin, graph2.xmax = xbounds
                graph2.ymin, graph2.ymax = ybounds

                plot = ContourPlot()
                plot.data = data
                plot.xrange = xbounds
                plot.yrange = ybounds
                plot.color = [1, 0.7, 0.2, 1]
                graph2.add_plot(plot)

                b.add_widget(graph2)
                self.contourplot = plot

                Clock.schedule_interval(self.update_contour, 1 / 60.)

            # Test the scatter plot
            plot = ScatterPlot(color=next(colors), point_size=5)
            graph.add_plot(plot)
            plot.points = [(x, .1 + randrange(10) / 10.) for x in range(-50, 1)]
            return b

        def make_contour_data(self, ts=0):
            omega = 2 * pi / 30
            k = (2 * pi) / 2.0

            ts = sin(ts * 2) + 1.5  # emperically determined 'pretty' values
            npoints = 100
            data = np.ones((npoints, npoints))

            position = [ii * 0.1 for ii in range(npoints)]
            time = [(ii % 100) * 0.6 for ii in range(npoints)]

            for ii, t in enumerate(time):
                for jj, x in enumerate(position):
                    data[ii, jj] = sin(
                        k * x + omega * t) + sin(-k * x + omega * t) / ts
            return (0, max(position)), (0, max(time)), data

        def update_points(self, *args):
            self.plot.points = [
                (x / 10., cos(Clock.get_time() + x / 50.))
                for x in range(-500, 501)]

        def update_contour(self, *args):
            _, _, self.contourplot.data[:] = self.make_contour_data(
                Clock.get_time())
            # this does not trigger an update, because we replace the
            # values of the arry and do not change the object.
            # However, we cannot do "...data = make_contour_data()" as
            # kivy will try to check for the identity of the new and
            # old values.  In numpy, 'nd1 == nd2' leads to an error
            # (you have to use np.all).  Ideally, property should be patched
            # for this.
            self.contourplot.ask_draw()

    TestApp().run()
