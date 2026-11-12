using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection.Metadata;
using System.Text;
using System.Threading.Tasks;
using CommonType;
using Dgcs.Comms.Mavlink;
using Dgcs.Comms.Models;
using Dgcs.Core.Dramas;
using Dgcs.Core.Models.Comms;
using Dgcs.Utils.Net;

namespace Dgcs.Comms.MavlinkMessages;

public class MavlinkCommandMessageBuilder
{
    private static readonly int minus_One = -1;

    public required IMavlinkParamSetHandler ParameterHandler { get; init; }

    /// <summary>
    /// 有不需要发送的包时，请返回null，而不是抛出异常，抛异常太耗性能
    /// </summary>
    public MavlinkMessage? MesgToMavlinkMsg(Cmd cmd)
    {
        MavlinkMessage? retMsg = null;

        switch (cmd.Id)
        {
            // 对于要接收 ACK 的命令，需要单独处理 ACK
            case MesgId.NewMessageOperation:
                {
                    if (cmd is CommsCommandRequest requestCmd)
                    {
                        return requestCmd.BuildMavlinkMessage(new CommsCommandBuildContext());
                    }
                    return null;
                }
                break;
            // 新的剧本开始传输指令（基于通用文件传输）
            case MesgId.MissionStart:
                {
                    var uavMsg = cmd as CmdMissionStart;
                    var mavMsg = new Msg_mission_request_start();
                    mavMsg.id = uavMsg.missionId;
                    mavMsg.index = 0;
                    mavMsg.type = 0; // 数据类型，航点/灯光等
                    mavMsg.count = 0; // 数据长度（e.g. 多少个航点灯光数据）
                    retMsg = mavMsg;
                }
                break;
            case MesgId.MissionVerify:
                {
                    var uavMsg = cmd as CmdMissionVerify;
                    var mavMsg = new Msg_mission_request_verify();
                    mavMsg.id = uavMsg.missionId;
                    mavMsg.type = uavMsg.MissionType switch
                    {
                        MissionType.Takeoff | MissionType.Fly | MissionType.Land => (byte)MAV_MISSION_TYPE.MAV_MISSION_TYPE_ALL,
                        MissionType.Takeoff | MissionType.Fly => (byte)MAV_MISSION_TYPE.MAV_MISSION_TYPE_DRAMA_ADD_TAKEOFF,
                        MissionType.Land | MissionType.Fly => (byte)MAV_MISSION_TYPE.MAV_MISSION_TYPE_DRAMA_ADD_LAND,
                        MissionType.Takeoff | MissionType.Land => (byte)MAV_MISSION_TYPE.MAV_MISSION_TYPE_LIGHT,
                        MissionType.Fly => (byte)MAV_MISSION_TYPE.MAV_MISSION_TYPE_DRAMA,
                        MissionType.Takeoff => (byte)MAV_MISSION_TYPE.MAV_MISSION_TYPE_TAKEOFF_LIGHT,
                        MissionType.Land => (byte)MAV_MISSION_TYPE.MAV_MISSION_TYPE_LAND_LIGHT,
                        _ => (byte)MAV_MISSION_TYPE.MAV_MISSION_TYPE_ALL, // ALL
                    };
                    mavMsg.crc32 = uavMsg.crc;
                    retMsg = mavMsg;
                }
                break;
            //case MesgId.WaypointStart:
            //    {
            //        var uavMsg = cmd as CmdWaypointStart;
            //        var mavMsg = new Msg_mission_request_start();
            //        mavMsg.id = uavMsg.missionId;
            //        mavMsg.index = 0;
            //        var type = MAV_MISSION_TYPE.MAV_MISSION_TYPE_WAYPOINT;
            //        if (uavMsg.type == LocationType.Return)
            //        {
            //            type = MAV_MISSION_TYPE.MAV_MISSION_TYPE_RETURNPOINT;
            //            mavMsg.index = (byte)uavMsg.dramaId;
            //        }

            //        mavMsg.type = (byte)type;
            //        mavMsg.count = (ushort)uavMsg.count; // 航点数量
            //        retMsg = mavMsg;
            //    }
            //    break;
            //case MesgId.WaypointUpload:
            //    {
            //        var uavMsg = cmd as CmdWaypointUpload;
            //        var mavMsg = new Msg_mission_data_waypoint();
            //        mavMsg.id = uavMsg.missionId;
            //        mavMsg.st_seq = (uint)uavMsg.start;
            //        mavMsg.ed_seq = (uint)uavMsg.end;
            //        mavMsg.lat = uavMsg.lats;
            //        mavMsg.lon = uavMsg.lons;
            //        mavMsg.alt = uavMsg.alts;
            //        mavMsg.crc32 = uavMsg.crc;
            //        retMsg = mavMsg;
            //    }
            //    break;
            //case MesgId.LightStart:
            //    {
            //        var uavMsg = cmd as CmdLightStart;
            //        var mavMsg = new Msg_mission_request_start();
            //        mavMsg.id = uavMsg.missionId;
            //        mavMsg.index = 0;
            //        var type = MAV_MISSION_TYPE.MAV_MISSION_TYPE_LIGHT;
            //        if (uavMsg.type == LightType.Takeoff)
            //        {
            //            type = MAV_MISSION_TYPE.MAV_MISSION_TYPE_TAKEOFF_LIGHT;
            //        }
            //        else if (uavMsg.type == LightType.Land)
            //        {
            //            type = MAV_MISSION_TYPE.MAV_MISSION_TYPE_LAND_LIGHT;
            //        }

            //        mavMsg.type = (byte)type;
            //        mavMsg.count = (ushort)uavMsg.count; // 灯光数量
            //        retMsg = mavMsg;
            //    }
            //    break;
            //case MesgId.LightUpload:
            //    {
            //        var uavMsg = cmd as CmdLightUpload;
            //        var mavMsg = new Msg_mission_data_light();
            //        mavMsg.id = uavMsg.missionId;
            //        mavMsg.st_seq = (uint)uavMsg.start;
            //        mavMsg.ed_seq = (uint)uavMsg.end;
            //        mavMsg.type = (byte)uavMsg.type;
            //        mavMsg.red = uavMsg.red;
            //        mavMsg.green = uavMsg.green;
            //        mavMsg.blue = uavMsg.blue;
            //        mavMsg.crc32 = uavMsg.crc;
            //        retMsg = mavMsg;
            //    }
            //    break;

            case MesgId.CommonFlightFile:
                {
                    var uavMsg = cmd as CommonFlightFileCmd;
                    var mavMsg = new Msg_net_file_command();

                    mavMsg.net_file_cmd = uavMsg.FileCommand;
                    mavMsg.data = uavMsg.Payload;
                    retMsg = mavMsg;
                }
                break;
            case MesgId.TransmitUpdate:
                {
                    var uavMsg = cmd as CmdUpdateFirmware;
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_UPDATE_COMPANION;
                    mavMsg.param1 = (int)uavMsg.updateType;
                    retMsg = mavMsg;
                }
                break;
            case MesgId.ArmDisarm:
                {
                    var uavMsg = cmd as CmdArmDisarm;
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_COMPONENT_ARM_DISARM;
                    mavMsg.param1 = uavMsg.arm ? 1 : 0;
                    return mavMsg;
                }
            case MesgId.FlightMode:
                {
                    var uavMsg = cmd as CmdFlightMode;
                    var mavMsg = new Msg_set_mode();
                    mavMsg.custom_mode = (uint)uavMsg.mode;
                    mavMsg.base_mode = 0x01;
                    mavMsg.target_system = 0x01;
                    return mavMsg;
                }
            case MesgId.LightMission:
                {
                    var uavMsg = cmd as CmdLightMission;
                    var mavMsg = new Msg_light_data();
                    mavMsg.start_time = uavMsg.startTime;
                    mavMsg.light_interval = uavMsg.light_Interval;
                    mavMsg.loop_count = uavMsg.loop_Count;
                    mavMsg.light_mode = uavMsg.light_Mode;
                    mavMsg.r0 = uavMsg.light.r;
                    mavMsg.g0 = uavMsg.light.g;
                    mavMsg.b0 = uavMsg.light.b;
                    mavMsg.r1 = uavMsg.r1;
                    mavMsg.g1 = uavMsg.g1;
                    mavMsg.b1 = uavMsg.b1;
                    mavMsg.r2 = uavMsg.r2;
                    mavMsg.g2 = uavMsg.g2;
                    mavMsg.b2 = uavMsg.b2;
                    mavMsg.data_count = uavMsg.data_Count;
                    mavMsg.data = uavMsg.data;
                    return mavMsg;
                }
            case MesgId.Takeoff:
                {
                    var uavMsg = cmd as CmdTakeoff;
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_NAV_TAKEOFF;
                    mavMsg.param1 = TntToMavFloat((int)(uavMsg.height * 1000));
                    mavMsg.param2 = TntToMavFloat((int)(uavMsg.target.lat * 1e7));
                    mavMsg.param3 = TntToMavFloat((int)(uavMsg.target.lon * 1e7));
                    mavMsg.param4 = TntToMavFloat((int)(uavMsg.target.alt * 1000));

                    return mavMsg;
                }
            case MesgId.Constrain:
                {
                    var uavMsg = cmd as CmdConstrain;
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_SET_RADIO_CTRL;
                    mavMsg.param1 = uavMsg.isOn ? TntToMavFloat(1) : TntToMavFloat(0);
                    return mavMsg;
                }
            case MesgId.SetParam:
                {
                    var uavMsg = cmd as CmdSetParams;
                    return ParameterHandler.BuildMavlinkParamSet(uavMsg);
                }
            case MesgId.GetParam:
                {
                    var uavMsg = cmd as CmdGetParams;
                    var mavMsg = new Msg_param_request_read() { param_id = new byte[128] };
                    for (int i = 0; i < uavMsg.paramKeys.Count; i++)
                    {
                        byte[] keyBytes = Encoding.ASCII.GetBytes(uavMsg.paramKeys[i]);
                        Array.Copy(keyBytes, 0, mavMsg.param_id, 16 * i, keyBytes.Length);
                    }

                    mavMsg.param_count = (ushort)uavMsg.paramKeys.Count;
                    mavMsg.target_component = 0x01;
                    mavMsg.target_system = 0x01;

                    return mavMsg;
                }
            case MesgId.RequireParamList:
                {
                    var mavMsg = new Msg_param_request_list();
                    mavMsg.target_component = 0x01;
                    mavMsg.target_system = 0x01;
                    return mavMsg;
                }
            case MesgId.FlightStartDelay:
                {
                    var uavMsg = cmd as CmdFlightStartDelay;
                    var mavMsg = new Msg_swarm_flight_start();
                    mavMsg.takeoff = uavMsg.takeoff;
                    mavMsg.play = uavMsg.play;
                    mavMsg.ascend = (int)(uavMsg.ascendHeight * 1000);
                    mavMsg.descend = (int)(uavMsg.descendHeight * 1000);
                    mavMsg.elevation = (int)(uavMsg.aslHeight * 1000);

                    mavMsg.final_mode = (byte)uavMsg.finalMode;
                    mavMsg.takeoff_light = uavMsg.takeoffLight.HasValue ? uavMsg.takeoffLight.Value : (ulong)minus_One;
                    mavMsg.land_light = uavMsg.landLight.HasValue ? uavMsg.landLight.Value : (ulong)minus_One;

                    mavMsg.return_lat = uavMsg.returnPointLat.HasValue ? (int)(uavMsg.returnPointLat.Value * 1e7) : minus_One;
                    mavMsg.return_lon = uavMsg.returnPointLon.HasValue ? (int)(uavMsg.returnPointLon.Value * 1e7) : minus_One;
                    mavMsg.return_elevation = uavMsg.returnElevation.HasValue ? (int)(uavMsg.returnElevation.Value * 1000) : minus_One;

                    mavMsg.play_id = uavMsg.flightId;
                    mavMsg.mission_id = uavMsg.taskId;

                    return mavMsg;
                }
            case MesgId.ClearLog:
                {
                    var mavMsg = new Msg_log_erase();
                    return mavMsg;
                }
            //case MesgId.FakeEkf:
            //    {
            //        var uavMsg = cmd as CommandFakeEkf;
            //        var mavMsg = new Msg_command_long();
            //        if (uavMsg.isSet)
            //        {
            //            mavMsg.command = (ushort)MAV_CMD.MAV_CMD_FAKE_EKF_FOR_TEST;
            //            mavMsg.param1 = (uavMsg.horz ? 1 : 0);
            //            mavMsg.param2 = (uavMsg.vert ? 1 : 0);
            //            mavMsg.param3 = (uavMsg.stab ? 1 : 0);
            //        }
            //        else
            //        {
            //            mavMsg.command = (ushort)MAV_CMD.MAV_CMD_RECOVER_EKF_FOR_TEST;
            //        }

            //        return mavMsg;
            //    }
            case MesgId.TestSensors:
                {
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_TEST_SENSORS;
                    return mavMsg;
                }
            case MesgId.ConsoleOut:
                {
                    var uavMsg = cmd as CmdConsoleOut;
                    var mavMsg = new Msg_console();
                    mavMsg.length = (byte)uavMsg.str.Length;
                    mavMsg.data = Encoding.ASCII.GetBytes(uavMsg.str);
                    return mavMsg;
                }
            case MesgId.ChangeNetworkConfig:
                {
                    var uavMsg = cmd as CmdChangeNetworkCfg;
                    var mavMsg = new Msg_euler_network();
                    if (!string.IsNullOrEmpty(uavMsg.ip))
                    {
                        mavMsg.id = IpAddressUtils.IpToId(uavMsg.ip);
                    }
                    if (uavMsg.ssid.Length > 8)
                    {
                        uavMsg.ssid = uavMsg.ssid.Substring(0, 8);
                    }
                    mavMsg.ssid = Encoding.ASCII.GetBytes(uavMsg.ssid);
                    return mavMsg;
                }
            case MesgId.Standby:
                {
                    var uavMsg = cmd as CmdSwitchPower;
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_STANDBY;
                    mavMsg.param1 = (int)uavMsg.type;
                    return mavMsg;
                }
            case MesgId.StandbyReady:
                {
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_STANDBY_READY;
                    return mavMsg;
                }
            case MesgId.CalibPeriph:
                {
                    var uavMsg = cmd as CmdCalibPeriph;
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_CALIB_SENSOR;
                    mavMsg.param2 = uavMsg.opType;
                    if (uavMsg.opType == 2)
                    {
                        mavMsg.param1 = 0;
                    }
                    else
                    {
                        switch (uavMsg.type)
                        {
                            case CalibrationType.ACCEL:
                                mavMsg.param1 = 1;
                                break;
                            case CalibrationType.CMPS:
                                mavMsg.param1 = 2;
                                break;
                            case CalibrationType.RC:
                                mavMsg.param1 = 3;
                                break;
                            case CalibrationType.ESC:
                                mavMsg.param1 = 4;
                                break;
                            case CalibrationType.UWB:
                                mavMsg.param1 = 5;
                                mavMsg.param3 = uavMsg.x;
                                mavMsg.param4 = uavMsg.y;
                                mavMsg.param5 = uavMsg.z;
                                break;
                            case CalibrationType.Camera:
                                mavMsg.param1 = 6;
                                break;
                            default:
                                mavMsg.param1 = 0;
                                break;
                        }
                    }
                    return mavMsg;
                }
            case MesgId.SetRemoteControl:
                {
                    var uavMsg = cmd as CmdSetRemoteControl;
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_SET_RC_GROUP;
                    mavMsg.param1 = uavMsg.RemoteControl?.Code ?? 0;
                    // rc_or_radio 为1切换成遥控器 ， rc_or_radio为2切换成电台，为 0 表示没有动作。
                    var rcOrRadio =  uavMsg.RcOrRadio.HasValue ? (uavMsg.RcOrRadio.Value ? 1 : 2) : 0;
                    mavMsg.param2 = rcOrRadio;
                    return mavMsg;
                }
            case MesgId.DifferentialInfo:
                {
                    var uavMsg = cmd as CmdDifferentialInfo;
                    dynamic mavMsg;
                    if (uavMsg.length < 32)
                    {
                        mavMsg = new Msg_differential_location_packet_32();
                        mavMsg.data = new byte[32];
                    }
                    else if (uavMsg.length < 128)
                    {
                        mavMsg = new Msg_differential_location_packet_128();
                        mavMsg.data = new byte[128];
                    }
                    else
                    {
                        mavMsg = new Msg_differential_location_packet_240();
                        mavMsg.data = new byte[240];
                    }

                    mavMsg.length = (byte)uavMsg.length;
                    mavMsg.seq = (uint)uavMsg.seq;
                    mavMsg.pack_num = (byte)uavMsg.subPacketCount;
                    mavMsg.subseq = (byte)uavMsg.subPacketIndex;
                    Array.ConstrainedCopy(uavMsg.info, 0, mavMsg.data, 0, mavMsg.length);
                    return mavMsg;
                }
            case MesgId.UavLogList:
                {
                    var mavMsg = new Msg_log_request_list();
                    return mavMsg;
                }
            case MesgId.UavLogDetail:
                {
                    var uavMsg = cmd as CmdUavLogDetail;
                    var mavMsg = new Msg_log_request_data();
                    mavMsg.id = uavMsg.id;
                    mavMsg.ofs = uavMsg.ofs;
                    mavMsg.count = uavMsg.size;
                    return mavMsg;
                }
            case MesgId.CalibTime:
                {
                    var uavMsg = new Msg_calib_time();
                    return uavMsg;
                }
            case MesgId.ChannelsRaw:
                {
                    var uavMsg = cmd as CmdChannelsRaw;
                    var mavMsg = new Msg_rc_channels_raw();

                    mavMsg.chan1_raw = uavMsg.ch1;
                    mavMsg.chan2_raw = uavMsg.ch2;
                    mavMsg.chan3_raw = uavMsg.ch3;
                    mavMsg.chan4_raw = uavMsg.ch4;
                    mavMsg.chan5_raw = uavMsg.ch5;
                    mavMsg.chan6_raw = uavMsg.ch6;
                    mavMsg.chan7_raw = uavMsg.ch7;
                    mavMsg.chan8_raw = uavMsg.ch8;
                    return mavMsg;
                }
            case MesgId.SetSerial:
                {
                    var uavMsg = cmd as CmdSetSerial;
                    var mavMsg = new Msg_set_serial_number();
                    mavMsg.serail_number = Encoding.ASCII.GetBytes(uavMsg.newSerial);
                    mavMsg.type = (byte)uavMsg.type;
                    return mavMsg;
                }
            case MesgId.SetCode:
                {
                    var uavMsg = cmd as CmdSetCode;
                    var mavMsg = new Msg_set_code_number();
                    mavMsg.code_number = Encoding.ASCII.GetBytes(uavMsg.newCode);
                    return mavMsg;
                }
            case MesgId.FirmwareInfo:
                {
                    var uavMsg = cmd as CmdFirmwareInfo;
                    var mavMsg = new Msg_submod_firmware_info();
                    mavMsg.submod_type = (byte)uavMsg.type;
                    mavMsg.spilt_sum = uavMsg.packageCount;
                    mavMsg.firmware_len = uavMsg.totalLength;
                    mavMsg.firmware_crc32 = uavMsg.crc;
                    return mavMsg;
                }
            case MesgId.UpdatePackage:
                {
                    var uavMsg = cmd as CmdPackageData;
                    var mavMsg = new Msg_submod_update_package();
                    mavMsg.package_seq = uavMsg.Seq;
                    mavMsg.package_data = uavMsg.Data;
                    return mavMsg;
                }
            case MesgId.CanArm:
                {
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_CAN_ARM;
                    return mavMsg;
                }
            case MesgId.SwitchDrama:
                {
                    var uavMsg = cmd as CmdSwitchDrama;
                    var mavMsg = new Msg_drama_switch();
                    mavMsg.type = (byte)uavMsg.type;
                    mavMsg.time = uavMsg.absoluteTime;
                    mavMsg.index = (byte)uavMsg.returnIndex;
                    mavMsg.final_mode = (byte)uavMsg.returnType;
                    return mavMsg;
                }
            case MesgId.SetUWBRackParam:
                {
                    var uavMsg = cmd as CmdSetUWBRackParam;
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_SET_UWB_ANCHOR;
                    mavMsg.param1 = uavMsg.param.ID;
                    mavMsg.param2 = uavMsg.param.N;
                    mavMsg.param3 = uavMsg.param.E;
                    mavMsg.param4 = uavMsg.param.Z;
                    mavMsg.param5 = uavMsg.param.Type;
                    mavMsg.param6 = uavMsg.param.Calib;
                    return mavMsg;
                }
            case MesgId.SetFence:
                {
                    var uavMsg = cmd as CmdSetFence;
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_DO_SET_FENCE;
                    mavMsg.param1 = uavMsg.locaion.ID;
                    mavMsg.param2 = TntToMavFloat((int)(uavMsg.locaion.Lat * 1e7));
                    mavMsg.param3 = TntToMavFloat((int)(uavMsg.locaion.Lon * 1e7));
                    mavMsg.param4 = uavMsg.locaion.Alt * 1000;
                    mavMsg.param5 = uavMsg.locaion.GroupId;
                    return mavMsg;
                }
            case MesgId.Return:
                {
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_RETURN_TYPE;
                    mavMsg.param1 = 0;
                    return mavMsg;
                }
            case MesgId.StopPlay:
                {
                    var uavMsg = cmd as CmdStopPlay;
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_FLIGHT_STOP;
                    mavMsg.param1 = uavMsg.type;
                    return mavMsg;
                }
            case MesgId.UpdateBoot:
                {
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_UPDATE_BOOT;
                    return mavMsg;
                }
            case MesgId.DynamicReturn:
                {
                    var uavMsg = cmd as CmdDynamicReturn;
                    var mavMsg = new Msg_drama_return();
                    mavMsg.time = uavMsg.time;
                    mavMsg.descend = uavMsg.descend;
                    return mavMsg;
                }
            case MesgId.RIDCTRL:
                {
                    var uavMsg = cmd as CmdRIDCTRL;
                    var mavMsg = new Msg_command_long();
                    mavMsg.command = (ushort)MAV_CMD.MAV_CMD_RID_CTRL;
                    mavMsg.param1 = (int)uavMsg.cmdType;
                    return mavMsg;
                }
            case MesgId.RIDSystemInfo:
                {
                    var uavMsg = cmd as CmdRidSystemInfo;
                    var mavMsg = new Msg_rid_system_info();
                    mavMsg.ID1 = Encoding.ASCII.GetBytes(uavMsg.operatorId);
                    mavMsg.ID2 = new byte[0];
                    mavMsg.ID3 = new byte[0];
                    mavMsg.lon = (int)(uavMsg.lon * 1e7);
                    mavMsg.lat = (int)(uavMsg.lat * 1e7);
                    mavMsg.alti = (int)(uavMsg.altitude * 1e3);
                    mavMsg.countryCode = Encoding.ASCII.GetBytes(uavMsg.CountryCode);
                    return mavMsg;
                }
            default:
                {
                    throw new InvalidOperationException($"[MavlinkCommandMessageBuilder] Unknown Message {cmd.GetType().Name} {cmd.Id}");
                }
        }

        return retMsg;
    }

    private float TntToMavFloat(int i)
    {
        var intBytes = BitConverter.GetBytes(i);
        return BitConverter.ToSingle(intBytes, 0);
    }

    private MAV_MISSION_TYPE GetMissionType(PacketType packetType)
    {
        var type = MAV_MISSION_TYPE.MAV_MISSION_TYPE_WAYPOINT;
        switch (packetType)
        {
            case PacketType.FlyLight:
                type = MAV_MISSION_TYPE.MAV_MISSION_TYPE_LIGHT;
                break;
            case PacketType.TakeoffLight:
                type = MAV_MISSION_TYPE.MAV_MISSION_TYPE_TAKEOFF_LIGHT;
                break;
            case PacketType.LandLight:
                type = MAV_MISSION_TYPE.MAV_MISSION_TYPE_LAND_LIGHT;
                break;
            case PacketType.WayPoint:
                type = MAV_MISSION_TYPE.MAV_MISSION_TYPE_WAYPOINT;
                break;
            //case PacketType.ReturnPoint:
            //    type = MAV_MISSION_TYPE.MAV_MISSION_TYPE_RETURNPOINT;
            //    break;
            default:
                throw new InvalidOperationException($"Unknow PacketType. {packetType}");
        }

        return type;
    }
}

public interface IMavlinkParamSetHandler
{
    Msg_param_set? BuildMavlinkParamSet(CmdSetParams uavMsg);
}
