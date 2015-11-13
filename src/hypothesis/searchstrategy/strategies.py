# coding=utf-8
#
# This file is part of Hypothesis (https://github.com/DRMacIver/hypothesis)
#
# Most of this work is copyright (C) 2013-2015 David R. MacIver
# (david@drmaciver.com), but it contains contributions by others. See
# https://github.com/DRMacIver/hypothesis/blob/master/CONTRIBUTING.rst for a
# full list of people who may hold copyright, and consult the git log if you
# need to determine who owns an individual contribution.
#
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.
#
# END HEADER

from __future__ import division, print_function, absolute_import

from hypothesis.errors import NoExamples, NoSuchExample
from hypothesis.control import assume
from hypothesis.internal.reflection import get_pretty_function_description
from hypothesis.internal.strategymethod import strategy as _strategy
from hypothesis.internal.conjecture.utils import integer_range

Infinity = float(u'inf')
EFFECTIVELY_INFINITE = 2 ** 32


def strategy(spec, settings=None):
    from hypothesis.settings import note_deprecation
    note_deprecation(
        'The strategy function is deprecated and will be removed in Hypothesis'
        ' 2.0. Please use the hypothesis.strategies module to construct your '
        'strategies', settings)
    return _strategy(spec, settings)

strategy.extend = _strategy.extend
strategy.extend_static = _strategy.extend_static


def one_of_strategies(xs):
    """Helper function for unioning multiple strategies."""
    xs = tuple(xs)
    if not xs:
        raise ValueError(u'Cannot join an empty list of strategies')
    if len(xs) == 1:
        return xs[0]
    return OneOfStrategy(xs)


class SearchStrategy(object):

    """A SearchStrategy is an object that knows how to explore data of a given
    type.

    Except where noted otherwise, methods on this class are not part of the
    public API and their behaviour may change significantly between minor
    version releases. They will generally be stable between patch releases.

    With that in mind, here is how SearchStrategy works.

    A search strategy is responsible for generating, simplifying and
    serializing examples for saving.

    In order to do this a strategy has three types (where type here is more
    precise than just the class of the value. For example a tuple of ints
    should be considered different from a tuple of strings):

    1. The strategy parameter type
    2. The strategy template type
    3. The generated type

    Of these, the first two should be considered to be private implementation
    details of a strategy and the only valid thing to do them is to pass them
    back to the search strategy. Additionally, templates may be compared for
    equality and hashed.

    Templates must be of quite a restricted type. A template may be any of the
    following:

    1. Any instance of the types bool, float, int, str (unicode on 2.7)
    2. None
    3. Any tuple or namedtuple of valid template types
    4. Any frozenset of valid template types

    This may be relaxed a bit in future, but the requirement that templates are
    hashable probably won't be.

    This may all seem overly complicated but it's for a fairly good reason.
    For more discussion of the motivation see
    http://hypothesis.readthedocs.org/en/master/internals.html

    Given these, data generation happens in three phases:

    1. Draw a parameter value from a random number (defined by
       draw_parameter)
    2. Given a parameter value and a Random, draw a random template
    3. Reify a template value, deterministically turning it into a value of
       the desired type.

    Data simplification proceeds on template values, taking a template and
    providing a generator over some examples of similar but simpler templates.

    """

    def example(self, random=None):
        """Provide an example of the sort of value that this strategy
        generates. This is biased to be slightly simpler than is typical for
        values from this strategy, for clarity purposes.

        This method shouldn't be taken too seriously. It's here for interactive
        exploration of the API, not for any sort of real testing.

        This method is part of the public API.

        """
        from hypothesis.core import find
        from hypothesis.settings import Settings
        try:
            return find(
                lambda x: True,
                random=random,
                settings=Settings(
                    max_shrinks=0,
                    max_iterations=100,
                    max_mutations=5,
                )
            )
        except NoSuchExample:
            raise NoExamples(
                u'Could not find any valid examples in 100 tries'
            )

    def map(self, pack):
        """Returns a new strategy that generates values by generating a value
        from this strategy and then calling pack() on the result, giving that.

        This method is part of the public API.

        """
        return MappedSearchStrategy(
            pack=pack, strategy=self
        )

    def flatmap(self, expand):
        """Returns a new strategy that generates values by generating a value
        from this strategy, say x, then generating a value from
        strategy(expand(x))

        This method is part of the public API.

        """
        from hypothesis.searchstrategy.flatmapped import FlatMapStrategy
        return FlatMapStrategy(
            expand=expand, strategy=self
        )

    def filter(self, condition):
        """Returns a new strategy that generates values from this strategy
        which satisfy the provided condition. Note that if the condition is too
        hard to satisfy this might result in your tests failing with
        Unsatisfiable.

        This method is part of the public API.

        """
        return FilteredStrategy(
            condition=condition,
            strategy=self,
        )

    def __or__(self, other):
        """Return a strategy which produces values by randomly drawing from one
        of this strategy or the other strategy.

        This method is part of the public API.

        """
        if not isinstance(other, SearchStrategy):
            raise ValueError(u'Cannot | a SearchStrategy with %r' % (other,))
        return one_of_strategies((self, other))

    def do_draw(self, data):
        raise NotImplementedError('%s.do_draw' % (type(self).__name__,))

    def __init__(self):
        pass


class OneOfStrategy(SearchStrategy):

    """Implements a union of strategies. Given a number of strategies this
    generates values which could have come from any of them.

    The conditional distribution draws uniformly at random from some non-empty
    subset of these strategies and then draws from the conditional distribution
    of that strategy.

    """

    def __init__(self,
                 strategies):
        SearchStrategy.__init__(self)
        strategies = tuple(strategies)
        if len(strategies) <= 1:
            raise ValueError(u'Need at least 2 strategies to choose amongst')
        self.element_strategies = list(strategies)

    def do_draw(self, data):
        return data.draw(self.element_strategies[
            integer_range(data, 0, len(self.element_strategies) - 1)])

    def __repr__(self):
        return u' | '.join(map(repr, self.element_strategies))


class MappedSearchStrategy(SearchStrategy):

    """A strategy which is defined purely by conversion to and from another
    strategy.

    Its parameter and distribution come from that other strategy.

    """

    def __init__(self, strategy, pack=None):
        SearchStrategy.__init__(self)
        self.mapped_strategy = strategy
        if pack is not None:
            self.pack = pack

    def __repr__(self):
        if not hasattr(self, u'_cached_repr'):
            self._cached_repr = u'%r.map(%s)' % (
                self.mapped_strategy, get_pretty_function_description(
                    self.pack)
            )
        return self._cached_repr

    def do_draw(self, data):
        return self.pack(self.mapped_strategy.do_draw(data))


class FilteredStrategy(SearchStrategy):

    def __init__(self, strategy, condition):
        super(FilteredStrategy, self).__init__()
        self.condition = condition
        self.filtered_strategy = strategy

    def __repr__(self):
        if not hasattr(self, u'_cached_repr'):
            self._cached_repr = u'%r.filter(%s)' % (
                self.filtered_strategy, get_pretty_function_description(
                    self.condition)
            )
        return self._cached_repr

    def do_draw(self, data):
        while True:
            start_index = data.index
            value = data.draw(self.filtered_strategy)
            if self.condition(value):
                return value
            else:
                # This is to guard against the case where we consume no data.
                # As long as we consume data, we'll eventually pass or raise.
                # But if we don't this could be an infinite loop.
                assume(data.index > start_index)
