// auto-generated from DavMessage.proto

using ProtoBuf;
using System.Collections.Generic;

namespace CommonType
{

    [ProtoContract()]
    public partial class UniversalCommand
    {
        [ProtoMember(1)]
        public uint Command { get; set; }

    }

    [ProtoContract()]
    public partial class SingleBytes
    {
        [ProtoMember(1)]
        public byte[] Msg { get; set; }

    }

    [ProtoContract()]
    public partial class EnrollRequest
    {
        [ProtoMember(1)]
        public OnlineDeviceType DeviceType { get; set; }

        [ProtoMember(2)]
        public string ProductName { get; set; }

        [ProtoMember(3)]
        public string SerialNumber { get; set; }

        [ProtoMember(4)]
        public uint Check { get; set; }

    }

    [ProtoContract()]
    public partial class EnrollReply
    {
        [ProtoMember(1)]
        public EnrollResult AcceptStatus { get; set; }

        [ProtoMember(2)]
        public uint HeartbeatIntervalMs { get; set; }

    }

    [ProtoContract()]
    public partial class PortableChargerHeartbeat
    {
        [ProtoMember(1)]
        public uint Soc { get; set; }

        [ProtoMember(2, IsPacked = true)]
        public float[] CellVoltages { get; set; }

        [ProtoMember(3)]
        public float SumVoltage { get; set; }

        [ProtoMember(4)]
        public float CellTemperature { get; set; }

        [ProtoMember(5)]
        public float FetTemperature { get; set; }

        [ProtoMember(6)]
        public float Current { get; set; }

        [ProtoMember(7)]
        public float DiffVol { get; set; }

        [ProtoMember(8)]
        public uint NormalFlag { get; set; }

        [ProtoMember(9)]
        public uint CycleCount { get; set; }

        [ProtoMember(10)]
        public float RechargeableTimes { get; set; }

        [ProtoMember(11)]
        public uint Soh { get; set; }

        [ProtoMember(12)]
        public uint ErrorCode { get; set; }

        [ProtoMember(13)]
        public bool FanOpen { get; set; }

        [ProtoMember(14)]
        public bool HeatOpen { get; set; }

        [ProtoMember(15)]
        public bool BazzOpen { get; set; }

        [ProtoMember(16)]
        public bool ChargeOpen { get; set; }

        [ProtoMember(17)]
        public bool DsOpen { get; set; }

        [ProtoMember(18)]
        public bool DischargeOpen { get; set; }

        [ProtoMember(19)]
        public uint ChargeStatus { get; set; }

        [ProtoMember(20)]
        public string WifiSsid { get; set; }

        [ProtoMember(21)]
        public string WifiIp { get; set; }

        [ProtoMember(22)]
        public uint OperationReg { get; set; }

        [ProtoMember(23)]
        public uint Lifetime { get; set; }

    }

    [ProtoContract()]
    public partial class PpsHeartBeat
    {
        [ProtoMember(1)]
        public SubDeviceType DeviceType { get; set; }

        [ProtoMember(2)]
        public FirmwareRunningStatus FirmwareRunningStatus { get; set; }

        [ProtoMember(3)]
        public string FirmwareVersionAlias { get; set; }

        [ProtoMember(4, DataFormat = DataFormat.FixedSize)]
        public uint FirmwareVersion { get; set; }

        [ProtoMember(5)]
        public uint ProtobufVersion { get; set; }

        [ProtoMember(6, DataFormat = DataFormat.FixedSize)]
        public uint LocalMsTime { get; set; }

        [ProtoMember(7)]
        public PortableChargerHeartbeat PortableCharger { get; set; }

    }

    [ProtoContract()]
    public partial class EncryptKey
    {
        [ProtoMember(1)]
        public uint EncryptType { get; set; }

        [ProtoMember(2)]
        public byte[] EncryptKeyValue { get; set; }

        [ProtoMember(3)]
        public byte[] EncryptIv { get; set; }

    }

    [ProtoContract()]
    public partial class RadioEncryptKey
    {
        [ProtoMember(1)]
        public EncryptKey RadioKey { get; set; }

        [ProtoMember(2)]
        public EncryptKey RcKey { get; set; }

    }

    [ProtoContract()]
    public partial class RFparameters
    {
        [ProtoMember(1)]
        public RadioRegulatoryDomain RfWorkMode { get; set; }

        [ProtoMember(2, IsPacked = true)]
        public uint[] RfTxPowerDbms { get; set; }

        [ProtoMember(3)]
        public uint RfTemperature { get; set; }

        /// <summary>
        /// 单位 Hz
        /// </summary>
        [ProtoMember(4, IsPacked = true)]
        public uint[] RfMaxFres { get; set; }

        /// <summary>
        /// 单位 Hz
        /// </summary>
        [ProtoMember(5, IsPacked = true)]
        public uint[] RfMinFres { get; set; }

    }

    [ProtoContract()]
    public partial class RadioStationRegulatoryDomain
    {
        [ProtoMember(1)]
        public uint SetDeviceId { get; set; }

        [ProtoMember(2)]
        public List<RFparameters> SetRfParams { get; } = new List<RFparameters>();

    }

    [ProtoContract(Name = @"rtkStationPosition")]
    public partial class RtkStationPosition
    {
        [ProtoMember(1)]
        public uint DeviceId { get; set; }

        [ProtoMember(2)]
        public double Latitude { get; set; }

        [ProtoMember(3)]
        public double Longitude { get; set; }

        [ProtoMember(4)]
        public double Altitude { get; set; }

    }

    [ProtoContract()]
    public partial class RadioButtonParam
    {
        [ProtoMember(1, IsPacked = true)]
        public uint[] LongClickTimes { get; set; }

        [ProtoMember(2, IsPacked = true)]
        public uint[] LongClickButtonModes { get; set; }

        [ProtoMember(3, IsPacked = true)]
        public uint[] ShortClickButtonModes { get; set; }

    }

    [ProtoContract(Name = @"radioStationR2HeartBeatExtend")]
    public partial class RadioStationR2HeartBeatExtend
    {
        [ProtoMember(1)]
        public uint DeviceId { get; set; }

        [ProtoMember(2)]
        public RadioR2ErrorValue ErrorReport { get; set; }

        [ProtoMember(3)]
        public string EthernetIp { get; set; }

        [ProtoMember(4)]
        public uint BatteryPercentage { get; set; }

        [ProtoMember(5)]
        public uint PoeVoltageMv { get; set; }

        [ProtoMember(6)]
        public uint ChargeTemperature { get; set; }

        [ProtoMember(7)]
        public uint GpsUtcTime { get; set; }

        [ProtoMember(8)]
        public List<RtkStationPosition> RadioGroupPositions { get; } = new List<RtkStationPosition>();

        [ProtoMember(9)]
        public List<RFparameters> RadioRfParams { get; } = new List<RFparameters>();

        [ProtoMember(10)]
        public RadioButtonParam ButtonParam { get; set; }

        [ProtoMember(11)]
        public uint EncryptType { get; set; }

        [ProtoMember(12)]
        public uint TranslateDataLeftBytes { get; set; }

    }

    [ProtoContract(Name = @"radioStationR2Heart")]
    public partial class RadioStationR2Heart
    {
        [ProtoMember(1)]
        public SubDeviceType DeviceType { get; set; }

        [ProtoMember(2)]
        public FirmwareRunningStatus FirmwareRunningStatus { get; set; }

        [ProtoMember(3)]
        public string FirmwareVersionAlias { get; set; }

        [ProtoMember(4, DataFormat = DataFormat.FixedSize)]
        public uint FirmwareVersion { get; set; }

        [ProtoMember(5)]
        public uint ProtobufVersion { get; set; }

        [ProtoMember(6, DataFormat = DataFormat.FixedSize)]
        public uint LocalMsTime { get; set; }

        [ProtoMember(7)]
        public RadioStationR2HeartBeatExtend RadioStationR2 { get; set; }

    }

    [ProtoContract()]
    public partial class RadioRFParamEcho
    {
        [ProtoMember(1, DataFormat = DataFormat.FixedSize)]
        public uint UpperFrequency { get; set; }

        [ProtoMember(2, DataFormat = DataFormat.FixedSize)]
        public uint LowerFrequency { get; set; }

        [ProtoMember(3, DataFormat = DataFormat.FixedSize)]
        public uint Bandwide { get; set; }

        [ProtoMember(4)]
        public uint FrequencyChannelNum { get; set; }

        [ProtoMember(5)]
        public float AverageTxPower { get; set; }

        [ProtoMember(6)]
        public uint SendDutyCycle { get; set; }

    }

    [ProtoContract()]
    public partial class RadioRFParamsEcho
    {
        [ProtoMember(1)]
        public List<RadioRFParamEcho> RfEchoes { get; } = new List<RadioRFParamEcho>();

    }

    [ProtoContract(Name = @"laserGimbalHeartExtend")]
    public partial class LaserGimbalHeartExtend
    {
        [ProtoMember(1)]
        public float Temperature { get; set; }

        [ProtoMember(2)]
        public uint ChannelStatus { get; set; }

        [ProtoMember(3)]
        public float CurRoll { get; set; }

        [ProtoMember(4)]
        public float CurPitch { get; set; }

    }

    [ProtoContract(Name = @"laserGimbalHeart")]
    public partial class LaserGimbalHeart
    {
        [ProtoMember(1)]
        public SubDeviceType DeviceType { get; set; }

        [ProtoMember(2)]
        public FirmwareRunningStatus RunningStatus { get; set; }

        [ProtoMember(3, DataFormat = DataFormat.FixedSize)]
        public uint FirmwareVersion { get; set; }

        [ProtoMember(4)]
        public uint ProtobufVersion { get; set; }

        [ProtoMember(5, DataFormat = DataFormat.FixedSize)]
        public uint LocalMsTime { get; set; }

        [ProtoMember(6)]
        public LaserGimbalHeartExtend GimbalExtendStatus { get; set; }

    }

    [ProtoContract()]
    public partial class FirmwareInfo
    {
        [ProtoMember(1)]
        public uint SplitLen { get; set; }

        [ProtoMember(2)]
        public uint SplitSum { get; set; }

        [ProtoMember(3, DataFormat = DataFormat.FixedSize)]
        public uint FirmwareVersion { get; set; }

        [ProtoMember(4, DataFormat = DataFormat.FixedSize)]
        public uint FirmwareLen { get; set; }

        [ProtoMember(5, DataFormat = DataFormat.FixedSize)]
        public uint HardwareCode { get; set; }

        [ProtoMember(6, DataFormat = DataFormat.FixedSize)]
        public uint FirmwareAddress { get; set; }

        [ProtoMember(7, DataFormat = DataFormat.FixedSize)]
        public uint FirmwareParamAddress { get; set; }

        [ProtoMember(8, DataFormat = DataFormat.FixedSize)]
        public uint FirmwareWriteAddress { get; set; }

        [ProtoMember(9)]
        public uint FirmwareType { get; set; }

        [ProtoMember(10)]
        public uint SecurityInfo { get; set; }

        [ProtoMember(11)]
        public byte[] FirmwareSha256 { get; set; }

    }

    [ProtoContract()]
    public partial class FirmwarePackage
    {
        [ProtoMember(1)]
        public uint PackageSeq { get; set; }

        [ProtoMember(2)]
        public byte[] FirmwareData { get; set; }

    }

    [ProtoContract()]
    public partial class DgcsControlPPS
    {
        [ProtoMember(1)]
        public uint ChgDischOpen { get; set; }

        [ProtoMember(2)]
        public uint FanOpen { get; set; }

        [ProtoMember(3)]
        public uint HeatOpen { get; set; }

        [ProtoMember(4)]
        public uint BazzOpen { get; set; }

        [ProtoMember(5)]
        public uint DsOpen { get; set; }

    }

    [ProtoContract()]
    public enum ProtoVersion
    {
        [ProtoEnum]
        Res = 0,
        [ProtoEnum]
        Version = 619934,
    }

    [ProtoContract()]
    public enum MessageID
    {
        [ProtoEnum]
        GetFirmwareVersion = 0,
        [ProtoEnum]
        AskDavAddress = 1,
        [ProtoEnum]
        SendDavAddress = 2,
        [ProtoEnum]
        ChangeDavAddress = 3,
        [ProtoEnum]
        AskChipUid = 4,
        [ProtoEnum]
        SendChipUid = 5,
        [ProtoEnum]
        SetProductSerialNumber = 6,
        [ProtoEnum]
        AskProductSerialNumber = 7,
        [ProtoEnum]
        SendProductSerialNumber = 8,
        [ProtoEnum]
        AskVersionSha = 9,
        [ProtoEnum]
        SendVersionSha = 10,
        [ProtoEnum]
        AskDavProtoVersionInt = 11,
        [ProtoEnum]
        EnrollRequest = 12,
        [ProtoEnum]
        EnrollReply = 13,
        [ProtoEnum]
        AskHeartbeat = 14,
        [ProtoEnum]
        PpsHeartbeat = 15,
        [ProtoEnum]
        SubmoduleTransSaveLog = 16,
        [ProtoEnum]
        AskDeviceLanConfig = 17,
        [ProtoEnum]
        SendDeviceLanConfig = 18,
        [ProtoEnum]
        SetDeviceLanConfig = 19,
        [ProtoEnum]
        AskHardfaultInfo = 20,
        [ProtoEnum]
        SendHardfaultInfo = 21,
        [ProtoEnum]
        RadioSendRtcm = 256,
        [ProtoEnum]
        RadioRtcmLinkInfo = 257,
        [ProtoEnum]
        SetRadioEncryptKey = 258,
        [ProtoEnum]
        AskRadioEncryptKey = 259,
        [ProtoEnum]
        SendRadioEncryptKey = 260,
        [ProtoEnum]
        RemoteControlSendChannel = 272,
        [ProtoEnum]
        SetRadioReceiverMode = 273,
        [ProtoEnum]
        RemoteControlFreqMatching = 274,
        [ProtoEnum]
        RemoteControlFreqMatchingResult = 275,
        [ProtoEnum]
        RadioReceiverRssi = 276,
        [ProtoEnum]
        RemoteControlReceiverRssi = 277,
        [ProtoEnum]
        GetReceiverRcAndRadioParam = 279,
        [ProtoEnum]
        SendReceiverRcAndRadioParam = 280,
        [ProtoEnum]
        SetReceiverRcAndRadioParam = 281,
        [ProtoEnum]
        AskDmdAutoTestStatus = 288,
        [ProtoEnum]
        ReceiverDmdAutoTestStatus = 289,
        [ProtoEnum]
        ElrsDmdAutoTestStatus = 290,
        [ProtoEnum]
        LoraRadioFactoryTest = 512,
        [ProtoEnum]
        AskRadioRegulatoryDomain = 513,
        [ProtoEnum]
        SendRadioRegulatoryDomain = 514,
        [ProtoEnum]
        SetRadioRegulatoryDomain = 515,
        [ProtoEnum]
        SendRadioR2Heartbeat = 516,
        [ProtoEnum]
        SetRadioButtonParam = 517,
        [ProtoEnum]
        SendRadioRfParamEcho = 519,
        [ProtoEnum]
        SendLaserGimbalHeartbeat = 640,
        [ProtoEnum]
        SendCurAttitude = 641,
        [ProtoEnum]
        SendCurGps = 642,
        [ProtoEnum]
        SetPayloadGimbalAngle = 643,
        [ProtoEnum]
        SetPayloadLaserChannel = 644,
        [ProtoEnum]
        SetPayloadNotifyLed = 645,
        [ProtoEnum]
        SetGimbalParam = 646,
        [ProtoEnum]
        SetGimbalCmd = 647,
        [ProtoEnum]
        ReadyToBootloader = 1058,
        [ProtoEnum]
        SendFirmwareHeader = 1061,
        [ProtoEnum]
        ControlMessageInBoot = 1062,
        [ProtoEnum]
        EraseFlashAddress = 1063,
        [ProtoEnum]
        SendFirmwarePacket = 1064,
        [ProtoEnum]
        SendFirmwareUpdateDone = 1067,
        [ProtoEnum]
        ReadyToJumpApp = 1068,
        [ProtoEnum]
        LppcControlMessage = 1536,
        [ProtoEnum]
        LppcBatteryMessage = 1537,
        [ProtoEnum]
        IctOnboardMessage = 1538,
        [ProtoEnum]
        LppcRegisterModifyMessage = 1539,
        [ProtoEnum]
        DgcsControlPpsMessage = 1792,
        [ProtoEnum]
        DisableReadProtect = 65533,
        [ProtoEnum]
        DroneHeader = 65537,
        [ProtoEnum]
        DroneFrame = 65538,
    }

    [ProtoContract()]
    public enum Uint32Value
    {
        [ProtoEnum]
        DavNoError = 0,
        [ProtoEnum]
        DavCommandAckBootloaderVersion = 1,
        [ProtoEnum]
        DavCommandAckAppVersion = 2,
        [ProtoEnum]
        DavCommandReturnToBootloader = 3,
        [ProtoEnum]
        DavCommandMessageDisableBroadcast = 4,
        [ProtoEnum]
        DavCommandMessageEnableBroadcast = 5,
        [ProtoEnum]
        DavCommandBootEraseFlashAddress = 6,
        [ProtoEnum]
        DavCommandAskDavAddress = 7,
        [ProtoEnum]
        DavCommandEnableRemoteControlFreqMatch = 8,
        [ProtoEnum]
        DavCommandDisableRemoteControlFreqMatch = 9,
        [ProtoEnum]
        DavCommandAskChipUid = 10,
        [ProtoEnum]
        DavCommandAskProductSerialNumber = 11,
        [ProtoEnum]
        DavCommandSet850mV3ReceiveMode = 12,
        [ProtoEnum]
        DavCommandSet850mR2ReceiveMode = 13,
        [ProtoEnum]
        DavCommandSet24gRemoteControlMode = 14,
        [ProtoEnum]
        DavCommandSet24gRtcmMode = 15,
        [ProtoEnum]
        DavCommandAskBootloaderSha256 = 16,
        [ProtoEnum]
        DavCommandAskAppSha256 = 17,
        [ProtoEnum]
        DavCommandAskProtocolSha256 = 18,
        [ProtoEnum]
        DavCommandAskProtoVersionInt = 19,
        [ProtoEnum]
        DavCommandAskRemoteControlMatchingCode = 20,
        [ProtoEnum]
        DavCommandAskRadioR2850mMatchingCode = 21,
        [ProtoEnum]
        DavCommandAskRadioR224gMatchingCode = 22,
        [ProtoEnum]
        DavCommandAckHeartbeat = 23,
        [ProtoEnum]
        DavCommandSet850mV3LowRateReceiveMode = 24,
        [ProtoEnum]
        DavCommandSet850mScanReceiveMode = 25,
        [ProtoEnum]
        DavCommandSet24gScanReceiveMode = 26,
        [ProtoEnum]
        DavCommandAskDeviceLanConfig = 27,
        [ProtoEnum]
        DavCommandAskLoraRadioWorkMode = 28,
        [ProtoEnum]
        DavCommandAckReceiverDmdAutoTestStatus = 30,
        [ProtoEnum]
        DavCommandAckElrsDmdAutoTestStatus = 31,
        [ProtoEnum]
        DavCommandAckHardfaultInfo = 32,
        [ProtoEnum]
        DavCommandSearchSubRadioStation = 33,
        [ProtoEnum]
        DavCommandCalibrateGimbal = 34,
        [ProtoEnum]
        DavCommandStorageGimbal = 35,
        [ProtoEnum]
        DavCommandWorkGimbal = 36,
        [ProtoEnum]
        DavCommandDebugGimbal = 37,
        [ProtoEnum]
        DavErrorProtobufDeserializeFail = 500,
        [ProtoEnum]
        DavErrorMemoryNoEnough = 501,
        [ProtoEnum]
        DavErrorInterfaceNotFound = 502,
        [ProtoEnum]
        DavErrorRouteAddressNotFound = 503,
        [ProtoEnum]
        DavErrorInterfaceIndexSetBeyond = 504,
        [ProtoEnum]
        DavErrorInterfaceIndexSetRepeat = 505,
        [ProtoEnum]
        DavErrorProductSerialNumFormatWrong = 506,
        [ProtoEnum]
        DavErrorProductSerialNumSetRepeat = 507,
        [ProtoEnum]
        DavStatusRemoteControlReceiverNoExist = 1000,
        [ProtoEnum]
        DavStatusRemoteControlReceiverInitFail = 1001,
        [ProtoEnum]
        DavStatusRemoteControlReceiverFreqMatchingTimeout = 1002,
        [ProtoEnum]
        DavStatusRemoteControlReceiverForeverLostSignal = 1003,
        [ProtoEnum]
        DavStatusRemoteControlReceiverTemporarilyLostSignal = 1004,
        [ProtoEnum]
        DavStatusRadio850mReceiverNoExist = 1010,
        [ProtoEnum]
        DavStatusRadio850mReceiverInitFail = 1011,
        [ProtoEnum]
        DavStatusRadio850mForeverLostSignal = 1012,
        [ProtoEnum]
        DavStatusRadio850mTemporarilyLostSignal = 1013,
        [ProtoEnum]
        DavStatusRadio2400mReceiverNoExist = 1020,
        [ProtoEnum]
        DavStatusRadio2400mReceiverInitFail = 1021,
        [ProtoEnum]
        DavStatusLppcControlReceiverNoExist = 1022,
        [ProtoEnum]
        DavStatusLppcControlReceiverInitFail = 1023,
        [ProtoEnum]
        DavStatusRadio2400mForeverLostSignal = 1024,
        [ProtoEnum]
        DavStatusRadio2400mTemporarilyLostSignal = 1025,
        [ProtoEnum]
        DavLppcModifyRegisterFailed = 1026,
        [ProtoEnum]
        DavReportRemoteControlFreqMatchSuccess = 2000,
        [ProtoEnum]
        DavReportRemoteControlFreqMatchTimeout = 2001,
    }

    [ProtoContract(Name = @"onlineDeviceType")]
    public enum OnlineDeviceType
    {
        [ProtoEnum]
        Uav = 0,
        [ProtoEnum]
        PortablePowerSource = 1,
        [ProtoEnum]
        RadioStation = 2,
    }

    [ProtoContract(Name = @"enrollResult")]
    public enum EnrollResult
    {
        [ProtoEnum]
        Accepted = 0,
        [ProtoEnum]
        Repeated = 1,
        [ProtoEnum]
        OutCapacity = 2,
        [ProtoEnum]
        CheckFail = 3,
        [ProtoEnum]
        SnError = 4,
    }

    [ProtoContract(Name = @"subDeviceType")]
    public enum SubDeviceType
    {
        [ProtoEnum]
        UavV4 = 0,
        [ProtoEnum]
        PortablePowerSourceV1 = 1,
        [ProtoEnum]
        RadioR2Station850m930mV1 = 2,
        [ProtoEnum]
        RadioR2Station2g4V1 = 3,
        [ProtoEnum]
        PayloadGimbal = 4,
        [ProtoEnum]
        RadioR2Station = 5,
    }

    [ProtoContract(Name = @"firmwareRunningStatus")]
    public enum FirmwareRunningStatus
    {
        [ProtoEnum]
        Normal = 0,
        [ProtoEnum]
        Updating = 1,
        [ProtoEnum]
        Standby = 2,
        [ProtoEnum]
        PowerOff = 3,
        [ProtoEnum]
        Calibrating = 4,
        [ProtoEnum]
        Emergency = 5,
    }

    [ProtoContract()]
    public enum RadioR2ErrorValue
    {
        [ProtoEnum]
        RadioR2NoError = 0,
        [ProtoEnum]
        RtkErrorValue = 1,
        [ProtoEnum]
        PowerButtonNotPressedValue = 2,
        [ProtoEnum]
        LowPowerValue = 4,
        [ProtoEnum]
        BatteryErrorValue = 8,
        [ProtoEnum]
        ChargeHighTemperatureValue = 16,
        [ProtoEnum]
        Radio850m930mHighTemperatureValue = 32,
        [ProtoEnum]
        Radio2g4TemperatureValue = 64,
        [ProtoEnum]
        Radio850m930mSelfTestErrorValue = 128,
        [ProtoEnum]
        Radio2g4SelfTestErrorValue = 256,
        [ProtoEnum]
        Radio850m930mIdConflictErrorValue = 512,
        [ProtoEnum]
        Radio2g4IdConflictErrorValue = 1024,
    }

    [ProtoContract()]
    public enum RadioR2ErrorBitValue
    {
        [ProtoEnum]
        RtkErrorBit = 0,
        [ProtoEnum]
        PowerButtonNotPressedBit = 1,
        [ProtoEnum]
        LowPowerBit = 2,
        [ProtoEnum]
        BatteryErrorBit = 3,
        [ProtoEnum]
        ChargeHighTemperatureBit = 4,
        [ProtoEnum]
        Radio850m930mHighTemperatureBit = 5,
        [ProtoEnum]
        Radio2g4TemperatureBit = 6,
        [ProtoEnum]
        Radio850m930mSelfTestErrorBit = 7,
        [ProtoEnum]
        Radio2g4SelfTestErrorBit = 8,
    }

    [ProtoContract(Name = @"radioFactoryTestCmd")]
    public enum RadioFactoryTestCmd
    {
        [ProtoEnum]
        AskFactoryMode = 0,
        [ProtoEnum]
        ReturnFactoryMode = 1,
        [ProtoEnum]
        SetFactoryMode = 2,
        [ProtoEnum]
        AskLLCC68RunMode = 100,
        [ProtoEnum]
        ReturnLLCC68RunMode = 101,
        [ProtoEnum]
        SetLLCC68RunMode = 102,
        [ProtoEnum]
        AskLLCC68Frequency = 103,
        [ProtoEnum]
        ReturnLLCC68Frequency = 104,
        [ProtoEnum]
        SetLLCC68Frequency = 105,
        [ProtoEnum]
        AskLLCC68PacketConfig = 106,
        [ProtoEnum]
        ReturnLLCC68PacketConfig = 107,
        [ProtoEnum]
        SetLLCC68PacketConfig = 108,
        [ProtoEnum]
        ReturnLLCC68PacketStatus = 109,
        [ProtoEnum]
        AskSX1280RunMode = 200,
        [ProtoEnum]
        ReturnSX1280RunMode = 201,
        [ProtoEnum]
        SetSX1280RunMode = 202,
        [ProtoEnum]
        AskSX1280Frequency = 203,
        [ProtoEnum]
        ReturnSX1280Frequency = 204,
        [ProtoEnum]
        SetSX1280Frequency = 205,
        [ProtoEnum]
        AskSX1280PacketConfig = 206,
        [ProtoEnum]
        ReturnSX1280PacketConfig = 207,
        [ProtoEnum]
        SetSX1280PacketConfig = 208,
        [ProtoEnum]
        ReturnSX1280PacketStatus = 209,
    }

    [ProtoContract(Name = @"radioRegulatoryDomain")]
    public enum RadioRegulatoryDomain
    {
        [ProtoEnum]
        CountryCodeMute = 0,
        [ProtoEnum]
        CountryCodeR1Mode = 2,
        [ProtoEnum]
        CountryCodeR1NewMode = 3,
        [ProtoEnum]
        CountryCodeEu869 = 4,
        [ProtoEnum]
        CountryCodeR2Ism2g4 = 5,
        [ProtoEnum]
        CountryCodeR2850m930m = 6,
        [ProtoEnum]
        CountryCodeRcIsm2g4 = 7,
        [ProtoEnum]
        CountryCodeR2Ism2g4ShortInterval = 8,
        [ProtoEnum]
        CountryCodeR1halfDutyMode = 9,
        [ProtoEnum]
        CountryCodeScan = 100,
        [ProtoEnum]
        CountryCodeFactoryTest = 101,
        [ProtoEnum]
        CountryCodeCw = 102,
        [ProtoEnum]
        CountryCodeCaliFreOffsetSned = 103,
        [ProtoEnum]
        CountryCodeCaliFreOffsetReceiver = 104,
        [ProtoEnum]
        CountryCodeRcBinding = 105,
    }

}

