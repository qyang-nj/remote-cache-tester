from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import BinaryIO

from .model import RpcCall


class GrpcLogError(RuntimeError):
    pass


class ProtobufWireReader:
    """Minimal protobuf decoder for Bazel's delimited RemoteExecutionLog."""

    @staticmethod
    def read_delimited(stream: BinaryIO) -> bytes | None:
        first = stream.read(1)
        if not first:
            return None
        size = ProtobufWireReader._read_varint_stream(stream, first[0])
        payload = stream.read(size)
        if len(payload) != size:
            raise GrpcLogError("truncated gRPC log entry")
        return payload

    @staticmethod
    def fields(payload: bytes) -> dict[int, list[int | bytes]]:
        fields: dict[int, list[int | bytes]] = defaultdict(list)
        offset = 0
        while offset < len(payload):
            key, offset = ProtobufWireReader._read_varint(payload, offset)
            field_number = key >> 3
            wire_type = key & 0x07
            if field_number == 0:
                raise GrpcLogError("invalid protobuf field number")

            if wire_type == 0:
                value, offset = ProtobufWireReader._read_varint(payload, offset)
            elif wire_type == 1:
                value, offset = ProtobufWireReader._read_fixed(payload, offset, 8)
            elif wire_type == 2:
                size, offset = ProtobufWireReader._read_varint(payload, offset)
                end = offset + size
                if end > len(payload):
                    raise GrpcLogError("truncated protobuf field")
                value = payload[offset:end]
                offset = end
            elif wire_type == 5:
                value, offset = ProtobufWireReader._read_fixed(payload, offset, 4)
            else:
                raise GrpcLogError(f"unsupported protobuf wire type {wire_type}")
            fields[field_number].append(value)
        return dict(fields)

    @staticmethod
    def _read_varint(payload: bytes, offset: int) -> tuple[int, int]:
        value = 0
        for shift in range(0, 70, 7):
            if offset >= len(payload):
                raise GrpcLogError("truncated protobuf varint")
            byte = payload[offset]
            offset += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value, offset
        raise GrpcLogError("protobuf varint is too long")

    @staticmethod
    def _read_varint_stream(stream: BinaryIO, first_byte: int) -> int:
        value = first_byte & 0x7F
        if not first_byte & 0x80:
            return value
        for shift in range(7, 70, 7):
            byte = stream.read(1)
            if not byte:
                raise GrpcLogError("truncated delimited protobuf size")
            value |= (byte[0] & 0x7F) << shift
            if not byte[0] & 0x80:
                return value
        raise GrpcLogError("delimited protobuf size is too long")

    @staticmethod
    def _read_fixed(payload: bytes, offset: int, size: int) -> tuple[bytes, int]:
        end = offset + size
        if end > len(payload):
            raise GrpcLogError("truncated fixed-width protobuf field")
        return payload[offset:end], end


class GrpcLogParser:
    METADATA_FIELD = 1
    STATUS_FIELD = 2
    METHOD_FIELD = 3
    DETAILS_FIELD = 4
    START_TIME_FIELD = 5
    END_TIME_FIELD = 6
    READ_DETAILS_FIELD = 5
    REQUEST_METADATA_TARGET_ID_FIELD = 6
    READ_REQUEST_FIELD = 1
    READ_REQUEST_RESOURCE_NAME_FIELD = 1

    def parse(self, path: Path) -> list[RpcCall]:
        calls: list[RpcCall] = []
        try:
            with path.open("rb") as stream:
                while (payload := ProtobufWireReader.read_delimited(stream)) is not None:
                    calls.append(self._parse_entry(payload))
        except OSError as error:
            raise GrpcLogError(f"cannot read {path}: {error}") from error
        return calls

    def _parse_entry(self, payload: bytes) -> RpcCall:
        fields = ProtobufWireReader.fields(payload)
        metadata = self._nested_fields(fields, self.METADATA_FIELD)
        method = self._bytes_field(fields, self.METHOD_FIELD).decode(
            "utf-8", errors="replace"
        )
        status = self._nested_fields(fields, self.STATUS_FIELD)
        details = self._nested_fields(fields, self.DETAILS_FIELD)
        start_time = self._timestamp(self._nested_fields(fields, self.START_TIME_FIELD))
        end_time = self._timestamp(self._nested_fields(fields, self.END_TIME_FIELD))

        bytes_read = 0
        resource_name = ""
        if method.endswith("ByteStream/Read") and self.READ_DETAILS_FIELD in details:
            read_details = ProtobufWireReader.fields(
                self._as_bytes(details[self.READ_DETAILS_FIELD][0])
            )
            bytes_read = self._int_field(read_details, 3)
            read_request = self._nested_fields(
                read_details, self.READ_REQUEST_FIELD
            )
            resource_name = self._bytes_field(
                read_request, self.READ_REQUEST_RESOURCE_NAME_FIELD
            ).decode("utf-8", errors="replace")

        return RpcCall(
            method=method,
            status_code=self._int_field(status, 1),
            start_time=start_time,
            end_time=end_time,
            bytes_read=bytes_read,
            target_id=self._bytes_field(
                metadata, self.REQUEST_METADATA_TARGET_ID_FIELD
            ).decode("utf-8", errors="replace"),
            resource_name=resource_name,
        )

    @staticmethod
    def _timestamp(fields: dict[int, list[int | bytes]]) -> float:
        seconds = GrpcLogParser._int_field(fields, 1)
        nanos = GrpcLogParser._int_field(fields, 2)
        return seconds + nanos / 1_000_000_000

    @staticmethod
    def _nested_fields(
        fields: dict[int, list[int | bytes]], field_number: int
    ) -> dict[int, list[int | bytes]]:
        if field_number not in fields:
            return {}
        return ProtobufWireReader.fields(
            GrpcLogParser._as_bytes(fields[field_number][0])
        )

    @staticmethod
    def _bytes_field(
        fields: dict[int, list[int | bytes]], field_number: int
    ) -> bytes:
        if field_number not in fields:
            return b""
        return GrpcLogParser._as_bytes(fields[field_number][0])

    @staticmethod
    def _int_field(
        fields: dict[int, list[int | bytes]], field_number: int
    ) -> int:
        if field_number not in fields:
            return 0
        value = fields[field_number][0]
        if not isinstance(value, int):
            raise GrpcLogError(f"protobuf field {field_number} is not an integer")
        return value

    @staticmethod
    def _as_bytes(value: int | bytes) -> bytes:
        if not isinstance(value, bytes):
            raise GrpcLogError("protobuf field is not length-delimited")
        return value
