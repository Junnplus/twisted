# -*- test-case-name: twisted.python.logger.test.test_format -*-
# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Tools for formatting logging events.
"""

from collections import defaultdict
from string import Formatter
from datetime import datetime as DateTime

from twisted.python.compat import unicode
from twisted.python.failure import Failure
from twisted.python.reflect import safe_repr
from twisted.python._tzhelper import FixedOffsetTimeZone

timeFormatRFC3339 = "%Y-%m-%dT%H:%M:%S%z"



def formatEvent(event):
    """
    Formats an event as a L{unicode}, using the format in
    C{event["log_format"]}.

    This implementation should never raise an exception; if the formatting
    cannot be done, the returned string will describe the event generically so
    that a useful message is emitted regardless.

    @param event: A logging event.
    @type event: L{dict}

    @return: A formatted string.
    @rtype: L{unicode}
    """
    try:
        if "log_flattened" in event:
            return flatFormat(event)

        format = event.get("log_format", None)

        if format is None:
            return u""

        # Make sure format is unicode.
        if isinstance(format, bytes):
            # If we get bytes, assume it's UTF-8 bytes
            format = format.decode("utf-8")

        elif isinstance(format, unicode):
            pass

        else:
            raise TypeError("Log format must be unicode or bytes, not {0!r}"
                            .format(format))

        return formatWithCall(format, event)

    except Exception as e:
        return formatUnformattableEvent(event, e)



def flatFormat(event):
    """
    Format an event which has been flattened with flattenEvent.

    @param event: A logging event.
    @type event: L{dict}

    @return: A formatted string.
    @rtype: L{unicode}
    """
    fields = event["log_flattened"]
    s = u""
    keyFlattener = KeyFlattener()

    for (
        literalText, fieldName, formatSpec, conversion
    ) in theFormatter.parse(event["log_format"]):

        s += literalText

        key = keyFlattener.flatKey(fieldName, formatSpec, conversion or "s")
        value = fields[key]

        s += unicode(value)

    return s



class KeyFlattener(object):
    """
    A L{KeyFlattener} computes keys for the things within curly braces in
    PEP-3101-style format strings as parsed by L{Formatter.parse}.
    """

    def __init__(self):
        """
        Initialize a L{KeyFlattener}.
        """
        self.keys = defaultdict(lambda: 0)


    def flatKey(self, fieldName, formatSpec, conversion):
        """
        Compute a string key for a given field/format/conversion.

        @param fieldName: A format field name.
        @type fieldName: L{str}

        @param formatSpec: A format spec.
        @type formatSpec: L{str}

        @param conversion: A format field conversion type.
        @type conversion: L{str}

        @return: A key specific to the given field, format and conversion, as
            well as the occurrence of that combination within this
            L{KeyFlattener}'s lifetime.
        @rtype: L{str}
        """
        result = (
            "{fieldName}!{conversion}:{formatSpec}"
            .format(
                fieldName=fieldName,
                formatSpec=(formatSpec or ""),
                conversion=(conversion or ""),
            )
        )
        self.keys[result] += 1
        n = self.keys[result]
        if n != 1:
            result += "/" + str(self.keys[result])
        return result



def flattenEvent(event):
    """
    Flatten the given event by pre-associating format fields with specific
    objects and callable results in a L{dict} put into the C{"log_flattened"}
    key in the event.

    @param event: A logging event.
    @type event: L{dict}
    """
    if "log_format" not in event:
        return
    fields = {}

    keyFlattener = KeyFlattener()

    for (literalText, fieldName, formatSpec, conversion) in (
            theFormatter.parse(event["log_format"])):
        if conversion != "r":
            conversion = "s"
        flattenedKey = keyFlattener.flatKey(fieldName, formatSpec, conversion)
        structuredKey = keyFlattener.flatKey(fieldName, formatSpec, "")
        if flattenedKey in fields:
            # We've already seen and handled this key
            continue

        if fieldName.endswith(u"()"):
            fieldName = fieldName[:-2]
            callit = True
        else:
            callit = False

        field = theFormatter.get_field(fieldName, (), event)
        fieldValue = field[0]
        if conversion == "s":
            conversionFunction = str
        elif conversion == "r":
            conversionFunction = repr
        else:
            conversion = "s"
            conversionFunction = lambda x: x
        if callit:
            fieldValue = fieldValue()
        flattenedValue = conversionFunction(fieldValue)
        fields[flattenedKey] = flattenedValue
        fields[structuredKey] = fieldValue

    event["log_flattened"] = fields



def extractField(field, event):
    """
    Extract a given format field from the given event.

    @param field: A string describing a format field or log key.  This is the
        text that would normally fall between a pair of curly braces in a
        format string: for example, C{"key[2].attribute"}.  If a conversion is
        specified (the thing after the C{"!"} character in a format field) then
        the result will always be L{unicode}.
    @type field: L{str} (native string)

    @param event: A log event.
    @type event: L{dict}

    @return: A value extracted from the field.
    @rtype: L{object}

    @raise KeyError: if the field is not found in the given event.
    """
    keyFlattener = KeyFlattener()
    [[literalText, fieldName, formatSpec, conversion]] = theFormatter.parse(
        "{" + field + "}"
    )
    key = keyFlattener.flatKey(fieldName, formatSpec, conversion)
    if "log_flattened" not in event:
        flattenEvent(event)
    return event["log_flattened"][key]



def formatUnformattableEvent(event, error):
    """
    Formats an event as a L{unicode} that describes the event generically and a
    formatting error.

    @param event: A logging event.
    @type event: L{dict}

    @param error: The formatting error.
    @type error: L{Exception}

    @return: A formatted string.
    @rtype: L{unicode}
    """
    try:
        return (
            u"Unable to format event {event!r}: {error}"
            .format(event=event, error=error)
        )
    except Exception:
        # Yikes, something really nasty happened.
        #
        # Try to recover as much formattable data as possible; hopefully at
        # least the namespace is sane, which will help you find the offending
        # logger.
        failure = Failure()

        text = u", ".join(u" = ".join((safe_repr(key), safe_repr(value)))
                          for key, value in event.items())

        return (
            u"MESSAGE LOST: unformattable object logged: {error}\n"
            u"Recoverable data: {text}\n"
            u"Exception during formatting:\n{failure}"
            .format(error=safe_repr(error), failure=failure, text=text)
        )



def formatTime(when, timeFormat=timeFormatRFC3339, default=u"-"):
    """
    Format a timestamp as text.

    Example::

        >>> from time import time
        >>> from twisted.python.logger import formatTime
        >>>
        >>> t = time()
        >>> formatTime(t)
        u'2013-10-22T14:19:11-0700'
        >>> formatTime(t, timeFormat="%Y/%W")  # Year and week number
        u'2013/42'
        >>>

    @param when: A timestamp.
    @type then: L{float}

    @param timeFormat: A time format.
    @type timeFormat: L{unicode} or C{None}

    @param default: Text to return if C{when} or C{timeFormat} is C{None}.
    @type default: L{unicode}

    @return: A formatted time.
    @rtype: L{unicode}
    """
    if (timeFormat is None or when is None):
        return default
    else:
        tz = FixedOffsetTimeZone.fromLocalTimeStamp(when)
        datetime = DateTime.fromtimestamp(when, tz)
        return unicode(datetime.strftime(timeFormat))



def formatEventAsClassicLogText(event, formatTime=formatTime):
    """
    Format an event as a line of human-readable text for, e.g. traditional log
    file output.

    The output format is C{u"{timeStamp} [{system}] {event}\\n"}, where:

        - C{timeStamp} is computed by calling the given C{formatTime} callable
          on the event's C{"log_time"} value

        - C{system} is the event's C{"log_system"} value, if set, otherwise,
          the C{"log_namespace"} and C{"log_level"}, joined by a C{u"#"}.  Each
          defaults to C{u"-"} is not set.

        - C{event} is the event, as formatted by L{formatEvent}.

    Example::

        >>> from __future__ import print_function
        >>> from time import time
        >>> from twisted.python.logger import formatEventAsClassicLogText
        >>> from twisted.python.logger import LogLevel
        >>>
        >>> formatEventAsClassicLogText(dict())  # No format, returns None
        >>> formatEventAsClassicLogText(dict(log_format=u"Hello!"))
        u'- [-#-] Hello!\\n'
        >>> formatEventAsClassicLogText(dict(
        ...     log_format=u"Hello!",
        ...     log_time=time(),
        ...     log_namespace="my_namespace",
        ...     log_level=LogLevel.info,
        ... ))
        u'2013-10-22T17:30:02-0700 [my_namespace#info] Hello!\\n'
        >>> formatEventAsClassicLogText(dict(
        ...     log_format=u"Hello!",
        ...     log_time=time(),
        ...     log_system="my_system",
        ... ))
        u'2013-11-11T17:22:06-0800 [my_system] Hello!\\n'
        >>>

    @param event: an event.
    @type event: L{dict}

    @param formatTime: A time formatter
    @type formatTime: L{callable} that takes an C{event} argument and returns
        a L{unicode}

    @return: A formatted event, or C{None} if no output is appropriate.
    @rtype: L{unicode} or C{None}
    """
    eventText = formatEvent(event)
    if not eventText:
        return None

    eventText = eventText.replace(u"\n", u"\n\t")
    timeStamp = formatTime(event.get("log_time", None))

    system = event.get("log_system", None)

    if system is None:
        level = event.get("log_level", None)
        if level is None:
            levelName = u"-"
        else:
            levelName = level.name

        system = u"{namespace}#{level}".format(
            namespace=event.get("log_namespace", u"-"),
            level=levelName,
        )
    else:
        try:
            system = unicode(system)
        except Exception:
            system = u"UNFORMATTABLE"

    return u"{timeStamp} [{system}] {event}\n".format(
        timeStamp=timeStamp,
        system=system,
        event=eventText,
    )



class CallMapping(object):
    """
    Read-only mapping that turns a C{()}-suffix in key names into an invocation
    of the key rather than a lookup of the key.

    Implementation support for L{formatWithCall}.
    """
    def __init__(self, submapping):
        """
        @param submapping: Another read-only mapping which will be used to look
            up items.
        """
        self._submapping = submapping


    def __getitem__(self, key):
        """
        Look up an item in the submapping for this L{CallMapping}, calling it
        if C{key} ends with C{"()"}.
        """
        callit = key.endswith(u"()")
        realKey = key[:-2] if callit else key
        value = self._submapping[realKey]
        if callit:
            value = value()
        return value



def formatWithCall(formatString, mapping):
    """
    Format a string like L{unicode.format}, but:

        - taking only a name mapping; no positional arguments

        - with the additional syntax that an empty set of parentheses
          correspond to a formatting item that should be called, and its result
          C{str}'d, rather than calling C{str} on the element directly as
          normal.

    For example::

        >>> formatWithCall("{string}, {function()}.",
        ...                dict(string="just a string",
        ...                     function=lambda: "a function"))
        'just a string, a function.'

    @param formatString: A PEP-3101 format string.
    @type formatString: L{unicode}

    @param mapping: A L{dict}-like object to format.

    @return: The string with formatted values interpolated.
    @rtype: L{unicode}
    """
    return unicode(
        theFormatter.vformat(formatString, (), CallMapping(mapping))
    )

theFormatter = Formatter()
