import typing

from dataclasses import field

import ezmsg.core as ez


class FrequencyMapperSettings(ez.Settings):
    mapping: typing.Dict[str, float] = field(default_factory = dict)


class FrequencyMapper(ez.Unit):
    SETTINGS = FrequencyMapperSettings

    INPUT_CLASS = ez.InputStream(typing.Optional[str])
    OUTPUT_FREQUENCY = ez.OutputStream(typing.Optional[float])

    @ez.subscriber(INPUT_CLASS)
    @ez.publisher(OUTPUT_FREQUENCY)
    async def on_class_input(self, msg: typing.Optional[str]) -> typing.AsyncGenerator:
        freq = None
        if msg is not None:
            freq = self.SETTINGS.mapping.get(msg, None)
        yield self.OUTPUT_FREQUENCY, freq