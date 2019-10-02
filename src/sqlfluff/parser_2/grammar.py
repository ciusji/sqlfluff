""" Definitions for Grammar """
import logging

from .segments_base import BaseSegment
from .segments_common import KeywordSegment
from .match import MatchResult


class BaseGrammar(object):
    """ Grammars are a way of composing match statements, any grammar
    must implment the `match` function. Segments can also be passed to
    most grammars. Segments implement `match` as a classmethod. Grammars
    implement it as an instance method """

    def __init__(self, *args, **kwargs):
        """ Deal with kwargs common to all grammars """
        # We provide a common interface for any grammar that allows positional elements
        self._elements = args
        # Now we deal with the standard kwargs
        for var, default in [('code_only', True), ('optional', False), ('terminal_hint', None)]:
            setattr(self, var, kwargs.pop(var, default))
        # optional, only really makes sense in the context of a sequence.
        # If a grammar is optional, then a sequence can continue without it.
        if kwargs:
            raise ValueError("Unconsumed kwargs is creation of grammar: {0}\nExcess: {1}".format(
                self.__class__.__name__,
                kwargs
            ))

    def is_optional(self):
        # The optional attribute is set in the __init__ method
        return self.optional

    def match(self, segments, match_depth=0, parse_depth=0):
        """
            Matching can be done from either the raw or the segments.
            This raw function can be overridden, or a grammar defined
            on the underlying class.
        """
        raise NotImplementedError("{0} has no match function implemented".format(self.__class__.__name__))

    def _match(self, segments, match_depth=0, parse_depth=0):
        """ A wrapper on the match function to do some basic validation """
        logging.info("[PD:{0} MD:{1}] {2}._match IN [ls={3}]".format(parse_depth, match_depth, self.__class__.__name__, len(segments)))
        if not isinstance(segments, (tuple, BaseSegment)):
            logging.warning(
                "{0}.match, was passed {1} rather than tuple or segment".format(
                    self.__class__.__name__, type(segments)))
            if isinstance(segments, list):
                # Let's make it a tuple for compatibility
                segments = tuple(segments)
        m = self.match(segments, match_depth=match_depth, parse_depth=parse_depth)
        if not isinstance(m, MatchResult):
            logging.warning(
                "{0}.match, returned {1} rather than MatchResult".format(
                    self.__class__.__name__, type(m)))
        logging.info("[PD:{0} MD:{1}] {2}._match OUT [m={3}]".format(parse_depth, match_depth, self.__class__.__name__, m))
        return m

    def expected_string(self):
        """ Return a String which is helpful to understand what this grammar expects """
        raise NotImplementedError(
            "{0} does not implement expected_string!".format(
                self.__class__.__name__))


class OneOf(BaseGrammar):
    """ Match any of the elements given once, if it matches
    multiple, it returns the first """
    def match(self, segments, match_depth=0, parse_depth=0):
        logging.debug("MATCH: {0}".format(self))
        # Match on each of the options
        matches = []
        for opt in self._elements:
            m = opt._match(segments, match_depth=match_depth + 1, parse_depth=parse_depth)
            # Do Type Munging using unify
            m = MatchResult.unify(m)
            matches.append(m)

        if sum([1 if m.has_match() else 0 for m in matches]) > 1:
            logging.warning("WARNING! Ambiguous match!")
        else:
            logging.debug(matches)

        for m in matches:
            if m.has_match():
                return m
        else:
            return MatchResult.from_unmatched(segments)

    def expected_string(self):
        return " | ".join([opt.expected_string() for opt in self._elements])


class GreedyUntil(BaseGrammar):
    """ See the match method desription for the full details """
    def match(self, segments, match_depth=0, parse_depth=0):
        """
        Matching for GreedyUntil works in a specific way for a specific reason.
        It's also a little counter intuitive, and would probably be better known
        as "DoesntContain" than Greedy Until.

        GreedyUntil(c)  on  abc     returns None
        GreedyUntil(d)  on  abc     returns abc
        GreedyUntil(a)  on  abc     returns None

        The reasoning for this is that we're assuming that we're probably within
        the context of a sequence which will retry with a shorter sequence if the match
        fails.
        """
        for seg in segments:
            for opt in self._elements:
                if opt._match(seg, match_depth=match_depth + 1, parse_depth=parse_depth):
                    # We've matched something. That means we should return empty
                    return MatchResult.from_unmatched(segments)
                else:
                    continue
        else:
            # We've got to the end without matching anything, so return.
            # We don't need to keep track of the match results, because
            # if any of them were usable, then we wouldn't be returning
            # anyway.
            return MatchResult.from_matched(segments)

    def expected_string(self):
        return "..., " + " !( " + " | ".join([opt.expected_string() for opt in self._elements]) + " ) "


class Sequence(BaseGrammar):
    """ Match a specific sequence of elements """

    def _terminal_hint(self, segments, matcher, code_only):
        """ A place to override for a whole class """
        return False

    def _get_terminal_hint_func(self):
        if self.terminal_hint:
            return self.terminal_hint
        else:
            return self._terminal_hint

    @staticmethod
    def _match_forward(segments, matcher, hint_func, code_only=True, match_depth=0, parse_depth=0):
        """ sequentially match shorter and shorter forward segments
        looking for arbitrary length matches. this function deals with
        skipping non code segments.
        UPDATE: Now starts with the longest, and go shorter. That's the make things
        work for the Delimited grammar especially. Used to start short and go long.
        UPDATE: We now allow a `terminal_hint` method, which if it's present and true,
        stops any further iteration. If it returns true then we terminate, if it returns an integer
        then it skips to that index."""
        # logging.debug("_match_forward: {0!r}, {1!r}".format(matcher, segments))
        # Check if the start of this sequence is code_only
        if code_only and not segments[0].is_code:
            # skip this one for matching, but add it to the match
            return (segments[0],), 1, False
        # Try decreasing lengths to match the remainder
        match_len = len(segments)
        while True:
            logging.debug("[PD:{0} MD:{1}] Forward Match (l={2}): {3}".format(parse_depth, match_depth, match_len, ''.join([seg.raw for seg in segments[:match_len]])))
            # logging.debug("_match_forward [loop]: {0!r}, {1!r}".format(matcher, segments[:match_len]))
            # Check for terminal hint
            hint = hint_func(segments[:match_len], matcher, code_only)
            if hint == True:
                print("Got TRUE hint")
                return None, 0, True
            elif hint == False:
                pass
            elif isinstance(hint, int):
                print("Got hint of {0}".format(hint))
                if hint < match_len:
                    match_len = hint
                else:
                    logging.warning("Ignoring hint - it seems longer the current match length?!")
            m = matcher._match(segments[:match_len], match_depth=match_depth + 1,
                               parse_depth=parse_depth)
            if m:
                # deal with the matches
                # advance the counter
                if isinstance(m, BaseSegment):
                    logging.warning("{0} returned a segment not a tuple!".format(matcher))
                    return (m,), match_len, True
                else:
                    return m, match_len, True
            match_len -= 1
            if match_len <= 0:
                return None, 0, True

    def match(self, segments, match_depth=0, parse_depth=0):
        print(
            "PD:{0} MD:{1} Entering {2}.match. expected: {3!r}\t\traw: {4!r}\t\tsegments: {5!r}".format(
                parse_depth,
                match_depth,
                self.__class__.__name__,
                self.expected_string(),
                ''.join([seg.raw for seg in segments]),
                BaseSegment.segs_to_tuple(segments, show_raw=True)))
        if isinstance(segments, BaseSegment):
            segments = tuple(segments)
        seg_idx = 0
        matched_segments = MatchResult.from_empty()
        for elem in self._elements:
            while True:
                if seg_idx >= len(segments):
                    # We've run our of sequence without matching everyting:
                    # is it optional?
                    if elem.is_optional():
                        # then it's ok
                        break
                    else:
                        logging.debug("{0}.match, failed to see match full sequence? Looking for non-optional: {1!r}".format(self.__class__.__name__, elem))
                        return MatchResult.from_empty()
                # sequentially try longer segments to see if it works.
                # We do this because the matcher might also be looking for
                # a sequence rather than a singular.
                m, n, c = self._match_forward(
                    segments=segments[seg_idx:], matcher=elem, hint_func=self._get_terminal_hint_func(),
                    code_only=self.code_only, match_depth=match_depth, parse_depth=parse_depth)
                if not m:
                    # We've failed to match at this index.
                    # Normally failing to match the next element in the
                    # sequence should return None directly, BUT if the element
                    # is optional then we may be able to move on.
                    if elem.is_optional():
                        logging.debug("{0}.match, skipping optional segment: {1!r}".format(self.__class__.__name__, elem))
                        break
                    else:
                        logging.debug("{0}.match, failed to find non-optional segment: {1!r}".format(self.__class__.__name__, elem))
                        return MatchResult.from_empty()
                else:
                    logging.debug("{0}.match, found: [n={1}] {2!r}".format(self.__class__.__name__, n, m))
                    matched_segments += m
                    # Advance the counter by the length of the match
                    if n <= 0:
                        raise ValueError("Advancing by zero: This means we'll loop infinitely!")
                    seg_idx += n
                    # If code only, then see if we've matched on code
                    if self.code_only:
                        if c:
                            # If code_only, and a code match, we should move on to the next element
                            break
                        else:
                            # If code_only, and not a code match, we should carry on with the same element
                            continue
                    else:
                        # If not code_only, then any match means we should advance the element
                        break
        else:
            # We've matched everything in the sequence, but we need to check FINALLY
            # if we've matched everything that was given.
            if seg_idx == len(segments):
                # If the segments get mutated we might need to do something different here
                return matched_segments
            elif self.code_only and all(not seg.is_code for seg in segments[seg_idx:]):
                # If we're only looking for code, and the only segments left are non-code
                # then be greedy
                return matched_segments + segments[seg_idx:]
            else:
                # We matched all the sequence, but the number of segments given was longer
                logging.debug("{0}.match, failed to match fully. Unmatched elements remain: {1!r}".format(self.__class__.__name__, segments[seg_idx:]))
                return MatchResult.from_empty()

    def expected_string(self):
        return ", ".join([opt.expected_string() for opt in self._elements])


class Delimited(Sequence):
    """ Match an arbitrary number of elements seperated by a delimiter """
    def __init__(self, *args, **kwargs):
        if 'delimiter' not in kwargs:
            raise ValueError("Delimited grammars require a `delimiter`")
        self.delimiter = kwargs.pop('delimiter')
        self.allow_trailing = kwargs.pop('allow_trailing', False)
        super(Delimited, self).__init__(*args, **kwargs)

    def match(self, segments, match_depth=0, parse_depth=0):
        if isinstance(segments, BaseSegment):
            segments = [segments]
        seg_idx = 0
        matched_segments = MatchResult.from_empty()
        looking_for = 'element'  # This will be `delimiter` when we find an element
        while True:
            if seg_idx >= len(segments):
                # We've got to the end of the segments, we can't end on a delimiter
                # unless allow_trailing is set
                if looking_for == 'element':
                    if self.allow_trailing:
                        return matched_segments
                    else:
                        return MatchResult.from_empty()
                elif looking_for == 'delimiter':
                    return matched_segments
                else:
                    raise ValueError("Unexpected looking for!")

            if looking_for == 'element':
                for elem in self._elements:
                    logging.debug("{0}.match, considering: {1!r}".format(self.__class__.__name__, elem))
                    m, n, c = self._match_forward(
                        segments=segments[seg_idx:], matcher=elem,
                        hint_func=self._get_terminal_hint_func(),
                        code_only=self.code_only,
                        match_depth=match_depth,
                        parse_depth=parse_depth)
                    if not m:
                        # We've failed to match at this index
                        continue
                    else:
                        logging.debug("{0}.match, found: [n={1}] {2!r}".format(self.__class__.__name__, n, m))
                        matched_segments += m
                        # Advance the counter by the length of the match
                        if n <= 0:
                            raise ValueError("Advancing by zero: This means we'll loop infinitely!")
                        seg_idx += n
                        # If we matched on code, then switch
                        if c:
                            looking_for = 'delimiter'
                        break
                else:
                    # Completed a loop without a match
                    logging.debug("{0}.match, no match [elem]".format(self.__class__.__name__))
                    return MatchResult.from_empty()
            elif looking_for == 'delimiter':
                logging.debug("{0}.match, considering: {1!r}".format(self.__class__.__name__, self.delimiter))
                m, n, c = self._match_forward(
                    segments=segments[seg_idx:], matcher=self.delimiter,
                    hint_func=self._get_terminal_hint_func(),
                    code_only=self.code_only,
                    match_depth=match_depth,
                    parse_depth=parse_depth)
                if m is None:
                    # We've failed to match at this index
                    logging.debug("{0}.match, no match [delim]".format(self.__class__.__name__))
                    return MatchResult.from_empty()
                else:
                    logging.debug("{0}.match, found: [n={1}] {2!r}".format(self.__class__.__name__, n, m))
                    matched_segments += m
                    # Advance the counter by the length of the match
                    if n <= 0:
                        raise ValueError("Advancing by zero: This means we'll loop infinitely!")
                    seg_idx += n
                    # If we matched on code, then switch
                    if c:
                        looking_for = 'element'
                    # NB: No break here, because we're not looping through options
            else:
                raise ValueError("Unexpected looking for: {0!r}".format(looking_for))

    def expected_string(self):
        return " {0} ".format(self.delimiter.expected_string()).join([opt.expected_string() for opt in self._elements])


class ContainsOnly(BaseGrammar):
    """ match a sequence of segments which are only of the types,
    or only match the grammars in the list """
    def match(self, segments, match_depth=0, parse_depth=0):
        seg_buffer = tuple()
        for seg in segments:
            matched = False
            if self.code_only and not seg.is_code:
                # Don't worry about non-code segments if we're configured
                # to do so.
                matched = True
                seg_buffer += (seg,)
            else:
                for opt in self._elements:
                    if isinstance(opt, str):
                        if seg.type == opt:
                            matched = True
                            seg_buffer += (seg,)
                            break
                    else:
                        try:
                            m = opt._match(seg, match_depth=match_depth + 1, parse_depth=parse_depth)
                        except AttributeError:
                            # This is unlikely, but if the element doesn't have a
                            # match method, then don't sweat. Just carry on.
                            continue
                        if m:
                            matched = True
                            seg_buffer += m
                            break
            if not matched:
                # Found a segment which doesn't match, this means
                # we fail the whole grammar because it doesn't just
                # contain only the given elements.
                return MatchResult.from_empty()
        else:
            return seg_buffer

    def expected_string(self):
        buff = []
        for opt in self._elements:
            if isinstance(opt, str):
                buff.append(opt)
            else:
                buff.append(opt.expected_string())
        return " ( " + " | ".join(buff) + " | + )"


class StartsWith(BaseGrammar):
    """ Match if the first element is the same, with configurable
    whitespace and comment handling """
    def __init__(self, target, *args, **kwargs):
        self.target = target
        super(StartsWith, self).__init__(*args, **kwargs)

    def match(self, segments, match_depth=0, parse_depth=0):
        if self.code_only:
            first_code = None
            first_code_idx = None
            for idx, seg in enumerate(segments):
                if seg.is_code:
                    first_code_idx = idx
                    first_code = seg
                    break
            else:
                return MatchResult.from_empty()

            match = self.target._match(segments=(first_code,), match_depth=match_depth + 1, parse_depth=parse_depth)
            if match:
                # The match will probably have returned a mutated version rather
                # that the raw segment sent for matching. We need to reinsert it
                # back into the sequence in place of the raw one, but we can't
                # just assign at the index because it's a tuple and not a list.
                # to get around that we do this slightly more elaborate construction.
                segments = segments[:first_code_idx] + tuple(match) + segments[first_code_idx + 1:]
                return MatchResult.from_matched(segments)
            else:
                return MatchResult.from_empty()
        else:
            raise NotImplementedError("Not expecting to match StartsWith and also not just code!?")

    def expected_string(self):
        return self.target.expected_string() + ", ..."


class Bracketed(Sequence):
    """ Bracketed is just a wrapper around Sequence """
    def __init__(self, *args, **kwargs):
        # Start and end tokens
        self.start_bracket = kwargs.pop(
            'start_bracket',
            KeywordSegment.make('(', name='start_bracket', type='start_bracket')
        )
        self.end_bracket = kwargs.pop(
            'end_bracket',
            KeywordSegment.make(')', name='end_bracket', type='end_bracket')
        )
        # Construct the sequence with brackets (as tuples)
        newargs = (self.start_bracket,) + args + (self.end_bracket,)
        # Call the sequence
        super(Bracketed, self).__init__(*newargs, **kwargs)

    def _terminal_hint(self, segments, matcher, code_only):
        """ A place to override for a whole class """
        # does it start with a bracket,
        for seg in segments:
            if self.start_bracket.match(seg):
                # ok we've got a start bracket
                break
            elif not seg.is_code and code_only:
                # this isn't code, move on
                continue
            else:
                # This starts with a segment which isn't a bracket
                return True
        else:
            # Don't know how we get here but it's bad
            return True

        bracket_stack = []
        for idx, seg in enumerate(segments):
            for raw in seg.iter_raw_seg():
                if self.start_bracket.match(raw):
                    bracket_stack.append(idx)
                elif self.end_bracket.match(raw):
                    if len(bracket_stack) == 1:
                        # We're on our last bracket, this should be the index to search for.
                        # TODO: Check whether this should be +1 or not.
                        return idx + 1
                    elif len(bracket_stack) <= 0:
                        # We should never get here
                        logging.warning("We should never get here: ID: A487AWHOL87AW3J")
                        return False
                    else:
                        bracket_stack.pop()

        # If we get to here, we never found the end bracket for the first opening one.
        # We should abort
        return False
