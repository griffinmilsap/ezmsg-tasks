import typing

from dataclasses import dataclass, field

from ezmsg.util.messages.axisarray import AxisArray
from ezmsg.sigproc.sampler import SampleTriggerMessage

@dataclass
class FrequencyDecodeMessage(AxisArray):
    freqs: typing.List[float] = field(default_factory = list)
    trigger: typing.Optional[SampleTriggerMessage] = None