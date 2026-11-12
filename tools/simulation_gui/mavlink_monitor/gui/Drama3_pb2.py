# -*- coding: utf-8 -*-
# Updated Drama3_pb2 — matches C# DramaProto.cs with all fields
# Extended from original to include rangeInfo, new payload types, etc.
"""Generated protocol buffer code (extended)."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import message as _message
from google.protobuf import reflection as _reflection
from google.protobuf import symbol_database as _symbol_database
import os as _os

_sym_db = _symbol_database.Default()

# Load descriptor from binary file (built to match C# DramaProto.cs)
_DESC_PATH = _os.path.join(_os.path.dirname(__file__), 'Drama3.desc')
with open(_DESC_PATH, 'rb') as _f:
    _DESC_BYTES = _f.read()

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(_DESC_BYTES)

# ── Message type references ──
_POSITIONKEYFRAME = DESCRIPTOR.message_types_by_name['PositionKeyFrame']
_POSEKEYFRAME = DESCRIPTOR.message_types_by_name['PoseKeyFrame']
_PAYLOADLIGHT = DESCRIPTOR.message_types_by_name['PayloadLight']
_PAYLOADLAZER = DESCRIPTOR.message_types_by_name['PayloadLazer']
_PAYLOADNOVA = DESCRIPTOR.message_types_by_name['PayloadNova']
_PAYLOADFIREWORKS = DESCRIPTOR.message_types_by_name['PayloadFireworks']
_PAYLOADFIREWORKANGLE = DESCRIPTOR.message_types_by_name['PayloadFireworkAngle']
_PAYLOADLANTERN = DESCRIPTOR.message_types_by_name['PayloadLantern']
_PAYLOADGIMBAL = DESCRIPTOR.message_types_by_name['PayloadGimbal']
_PAYLOADGIMBALVECTOR = DESCRIPTOR.message_types_by_name['PayloadGimbalVector']
_PAYLOADLIGHTFRAME = DESCRIPTOR.message_types_by_name['PayloadLightFrame']
_PAYLOADNOVAFRAME = DESCRIPTOR.message_types_by_name['PayloadNovaFrame']
_PAYLOADFIREWORKSFRAME = DESCRIPTOR.message_types_by_name['PayloadFireworksFrame']
_PAYLOADLANTERNFRAME = DESCRIPTOR.message_types_by_name['PayloadLanternFrame']
_PAYLOADGIMBALFRAME = DESCRIPTOR.message_types_by_name['PayloadGimbalFrame']
_PAYLOADLAZERFRAME = DESCRIPTOR.message_types_by_name['PayloadLazerFrame']
_PAYLOADPARACHUTE = DESCRIPTOR.message_types_by_name['PayloadParachute']
_PAYLOADPARACHUTEFRAME = DESCRIPTOR.message_types_by_name['PayloadParachuteFrame']
_PAYLOADFOLDLANTERN = DESCRIPTOR.message_types_by_name['PayloadFoldLantern']
_PAYLOADFOLDLANTERNFRAME = DESCRIPTOR.message_types_by_name['PayloadFoldLanternFrame']
_PAYLOADKONGMINGLANTERN = DESCRIPTOR.message_types_by_name['PayloadKongMingLantern']
_PAYLOADKONGMINGLANTERNFRAME = DESCRIPTOR.message_types_by_name['PayloadKongMingLanternFrame']
_PAYLOADPEACHLANTERN = DESCRIPTOR.message_types_by_name['PayloadPeachLantern']
_PAYLOADPEACHLANTERNFRAME = DESCRIPTOR.message_types_by_name['PayloadPeachLanternFrame']
_PAYLOADFISHLANTERN = DESCRIPTOR.message_types_by_name['PayloadFishLantern']
_PAYLOADFISHLANTERNFRAME = DESCRIPTOR.message_types_by_name['PayloadFishLanternFrame']
_PAYLOADCONFETTI = DESCRIPTOR.message_types_by_name['PayloadConfetti']
_PAYLOADCONFETTIFRAME = DESCRIPTOR.message_types_by_name['PayloadConfettiFrame']
_VECTOR3PROTO = DESCRIPTOR.message_types_by_name['Vector3Proto']
_LASERAREAPROTO = DESCRIPTOR.message_types_by_name['LaserAreaProto']
_DRAMARANGEINFO = DESCRIPTOR.message_types_by_name['DramaRangeInfo']
_DRONE = DESCRIPTOR.message_types_by_name['Drone']
_MAPINFO = DESCRIPTOR.message_types_by_name['MapInfo']
_SEGMENTINFO = DESCRIPTOR.message_types_by_name['SegmentInfo']
_DRAMA3 = DESCRIPTOR.message_types_by_name['Drama3']

# ── Register message classes ──
def _make_msg(name, desc):
    return _reflection.GeneratedProtocolMessageType(name, (_message.Message,), {
        'DESCRIPTOR': desc,
        '__module__': 'Drama3_pb2'
    })

PositionKeyFrame = _make_msg('PositionKeyFrame', _POSITIONKEYFRAME)
_sym_db.RegisterMessage(PositionKeyFrame)

PoseKeyFrame = _make_msg('PoseKeyFrame', _POSEKEYFRAME)
_sym_db.RegisterMessage(PoseKeyFrame)

PayloadLight = _make_msg('PayloadLight', _PAYLOADLIGHT)
_sym_db.RegisterMessage(PayloadLight)

PayloadLazer = _make_msg('PayloadLazer', _PAYLOADLAZER)
_sym_db.RegisterMessage(PayloadLazer)

PayloadNova = _make_msg('PayloadNova', _PAYLOADNOVA)
_sym_db.RegisterMessage(PayloadNova)

PayloadFireworks = _make_msg('PayloadFireworks', _PAYLOADFIREWORKS)
_sym_db.RegisterMessage(PayloadFireworks)

PayloadFireworkAngle = _make_msg('PayloadFireworkAngle', _PAYLOADFIREWORKANGLE)
_sym_db.RegisterMessage(PayloadFireworkAngle)

PayloadLantern = _make_msg('PayloadLantern', _PAYLOADLANTERN)
_sym_db.RegisterMessage(PayloadLantern)

PayloadGimbal = _make_msg('PayloadGimbal', _PAYLOADGIMBAL)
_sym_db.RegisterMessage(PayloadGimbal)

PayloadGimbalVector = _make_msg('PayloadGimbalVector', _PAYLOADGIMBALVECTOR)
_sym_db.RegisterMessage(PayloadGimbalVector)

PayloadLightFrame = _make_msg('PayloadLightFrame', _PAYLOADLIGHTFRAME)
_sym_db.RegisterMessage(PayloadLightFrame)

PayloadNovaFrame = _make_msg('PayloadNovaFrame', _PAYLOADNOVAFRAME)
_sym_db.RegisterMessage(PayloadNovaFrame)

PayloadFireworksFrame = _make_msg('PayloadFireworksFrame', _PAYLOADFIREWORKSFRAME)
_sym_db.RegisterMessage(PayloadFireworksFrame)

PayloadLanternFrame = _make_msg('PayloadLanternFrame', _PAYLOADLANTERNFRAME)
_sym_db.RegisterMessage(PayloadLanternFrame)

PayloadGimbalFrame = _make_msg('PayloadGimbalFrame', _PAYLOADGIMBALFRAME)
_sym_db.RegisterMessage(PayloadGimbalFrame)

PayloadLazerFrame = _make_msg('PayloadLazerFrame', _PAYLOADLAZERFRAME)
_sym_db.RegisterMessage(PayloadLazerFrame)

PayloadParachute = _make_msg('PayloadParachute', _PAYLOADPARACHUTE)
_sym_db.RegisterMessage(PayloadParachute)

PayloadParachuteFrame = _make_msg('PayloadParachuteFrame', _PAYLOADPARACHUTEFRAME)
_sym_db.RegisterMessage(PayloadParachuteFrame)

PayloadFoldLantern = _make_msg('PayloadFoldLantern', _PAYLOADFOLDLANTERN)
_sym_db.RegisterMessage(PayloadFoldLantern)

PayloadFoldLanternFrame = _make_msg('PayloadFoldLanternFrame', _PAYLOADFOLDLANTERNFRAME)
_sym_db.RegisterMessage(PayloadFoldLanternFrame)

PayloadKongMingLantern = _make_msg('PayloadKongMingLantern', _PAYLOADKONGMINGLANTERN)
_sym_db.RegisterMessage(PayloadKongMingLantern)

PayloadKongMingLanternFrame = _make_msg('PayloadKongMingLanternFrame', _PAYLOADKONGMINGLANTERNFRAME)
_sym_db.RegisterMessage(PayloadKongMingLanternFrame)

PayloadPeachLantern = _make_msg('PayloadPeachLantern', _PAYLOADPEACHLANTERN)
_sym_db.RegisterMessage(PayloadPeachLantern)

PayloadPeachLanternFrame = _make_msg('PayloadPeachLanternFrame', _PAYLOADPEACHLANTERNFRAME)
_sym_db.RegisterMessage(PayloadPeachLanternFrame)

PayloadFishLantern = _make_msg('PayloadFishLantern', _PAYLOADFISHLANTERN)
_sym_db.RegisterMessage(PayloadFishLantern)

PayloadFishLanternFrame = _make_msg('PayloadFishLanternFrame', _PAYLOADFISHLANTERNFRAME)
_sym_db.RegisterMessage(PayloadFishLanternFrame)

PayloadConfetti = _make_msg('PayloadConfetti', _PAYLOADCONFETTI)
_sym_db.RegisterMessage(PayloadConfetti)

PayloadConfettiFrame = _make_msg('PayloadConfettiFrame', _PAYLOADCONFETTIFRAME)
_sym_db.RegisterMessage(PayloadConfettiFrame)

Vector3Proto = _make_msg('Vector3Proto', _VECTOR3PROTO)
_sym_db.RegisterMessage(Vector3Proto)

LaserAreaProto = _make_msg('LaserAreaProto', _LASERAREAPROTO)
_sym_db.RegisterMessage(LaserAreaProto)

DramaRangeInfo = _make_msg('DramaRangeInfo', _DRAMARANGEINFO)
_sym_db.RegisterMessage(DramaRangeInfo)

Drone = _make_msg('Drone', _DRONE)
_sym_db.RegisterMessage(Drone)

MapInfo = _make_msg('MapInfo', _MAPINFO)
_sym_db.RegisterMessage(MapInfo)

SegmentInfo = _make_msg('SegmentInfo', _SEGMENTINFO)
_sym_db.RegisterMessage(SegmentInfo)

Drama3 = _make_msg('Drama3', _DRAMA3)
_sym_db.RegisterMessage(Drama3)

# @@protoc_insertion_point(module_scope)
