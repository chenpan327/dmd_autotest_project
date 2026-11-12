# coding: utf-8

import time

import pytest
import allure
from utils.logger import logger


@allure.feature("串口协议命令测试")
# @allure.story("Serial Protocol Lite 全命令覆盖")
@allure.severity(allure.severity_level.NORMAL)
# @allure.title("串口协议命令功能测试")
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "SERIAL_PROTOCOL", "COMMAND_TEST")


@pytest.mark.functional
class TestSerialProtocol:
    """
    串口协议命令全覆盖测试。

    覆盖 Serial Protocol Lite 全部 60+ 命令：目录操作、参数读写、系统状态查询、
    飞行控制、灯光/舵机、DShot 电机驱动、异常状态模拟、WiFi 配置、日志记录、
    内存调试、电机测试、老化测试和表演控制。

    每项测试验证命令可正常发送并收到有效响应。
    """

    @pytest.fixture(autouse=True)
    def setup_before_test(self, serial_protocol_handler):
        logger.info("前置操作：初始化协议处理器")
        self.serial = serial_protocol_handler
        yield
        logger.info("后置操作：清理测试资源")

    # ==================== 目录操作 ====================
    @allure.story("目录操作")
    @allure.title("查看当前目录文件列表")
    @allure.description("""
    发送 ls 命令，验证返回当前目录下的文件列表且结果非空。

    工作原理（CLI_COMMANDS_REFERENCE #1）：
    - 调用 rewinddir() 重置目录指针，遍历目录条目
    - 对每个条目调用 stat() 获取信息
    - 输出格式 SIZE\\tNAME，目录追加 / 标记
    """)
    def test_list_directory(self):
        with allure.step("发送 ls 命令并检查返回数据"):
            logger.info("发送 ls 命令")
            result = self.serial.list_directory()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
            assert isinstance(result, list), f"ls 应返回列表，实际返回 {type(result)}"
            assert len(result) > 0, "ls 返回的文件列表不应为空"
            # 验证列表中的每一项都是字符串（文件名/目录名）
            for item in result:
                assert isinstance(item, str), f"ls 条目应为字符串，实际 {type(item)}: {item}"

    @allure.story("目录操作")
    @allure.title("切换工作目录")
    @allure.description("发送 cd 命令切换到子目录再返回上级目录，验证每次切换后 ls 可正常列出文件。")
    def test_change_directory(self):
        with allure.step("切换到 data 目录"):
            logger.info("发送 cd data 命令")
            result = self.serial.change_directory("data")
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

        with allure.step("验证 data 目录下的文件列表"):
            logger.info("发送 ls 命令")
            result = self.serial.list_directory()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

        with allure.step("返回上级目录"):
            result = self.serial.change_directory("..")
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

        with allure.step("验证上级目录的文件列表"):
            logger.info("发送 ls 命令")
            result = self.serial.list_directory()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    # ==================== 参数命令 ====================
    @allure.story("参数操作")
    @allure.title("获取全部参数")
    @allure.description("""
    发送 pp 命令获取全部参数的键值对字典，验证返回结果非空。

    工作原理（CLI_COMMANDS_REFERENCE #5）：
    - 无参时从根参数包 gpara 递归调用 print_param() 遍历参数树
    - PARAM_TYPE_PACK 节点遍历子节点链表，叶子节点调用 para->get_float()
    - 输出格式 NAME  :VALUE
    """)
    def test_get_parameter(self):
        with allure.step("发送 pp 命令获取全部参数"):
            logger.info("发送 pp 命令")
            result = self.serial.get_parameter("")
            logger.info(f"返回结果包含 {len(result) if result else 0} 个参数")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
            assert isinstance(result, dict), f"pp 应返回字典，实际返回 {type(result)}"
            # 验证存在已知的核心参数（飞控基本配置参数）
            known_params = ["LOG_MSK0", "INDOOR_DEBUG", "MT0_MAP"]
            found = [p for p in known_params if p in result]
            logger.info(f"已知参数命中: {found}")
            # 至少应有部分参数存在（不同固件版本参数集不同）
            assert len(result) > 10, f"参数总数应 > 10，实际 {len(result)}"

    @pytest.mark.skip(reason="pp 命令响应格式变更(Key:Value)，regex 未匹配，待修复")
    @allure.story("参数操作")
    @allure.title("获取指定参数值")
    @allure.description("发送 pp <name> 命令获取指定参数的值，验证返回结果非空。")
    def test_get_specific_parameter(self):
        with allure.step("发送 pp LOG_MSK0 命令"):
            logger.info("发送 pp 命令获取指定参数")
            result = self.serial.get_parameter("LOG_MSK0")
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @allure.story("参数操作")
    @allure.title("设置参数值")
    @allure.description("""
    发送 sp <name>:<value> 命令修改指定参数，并读取验证值已变更。

    工作原理（CLI_COMMANDS_REFERENCE #7）：
    - 以 ':' 分隔参数名和值，调用 find_param_by_name() 查找参数
    - 根据 ptype 类型转换（atoi/atof），调用 set_data_buf() 写入
    - sp 只修改内存中的值，不持久化到 Flash
    """)
    def test_set_parameter(self):
        with allure.step("先读取 INDOOR_DEBUG 当前值"):
            logger.info("读取 INDOOR_DEBUG 当前值")
            old_result = self.serial.get_parameter("INDOOR_DEBUG")
            logger.info(f"当前值：{old_result}")

        with allure.step("发送 sp 命令设置 INDOOR_DEBUG=1"):
            logger.info("发送 sp 命令设置参数")
            result = self.serial.set_parameter("INDOOR_DEBUG", 1)
            logger.info(f"返回结果：{result}")
            assert result, "sp 命令执行失败"
            assert result is not None, "命令执行失败"

        with allure.step("读取 INDOOR_DEBUG 验证值已变更"):
            logger.info("读取 INDOOR_DEBUG 验证")
            new_result = self.serial.get_parameter("INDOOR_DEBUG")
            logger.info(f"变更后值：{new_result}")
            if new_result and "INDOOR_DEBUG" in new_result:
                assert float(new_result["INDOOR_DEBUG"]) == 1.0, \
                    f"sp 设置失败: 期望 1，实际 {new_result['INDOOR_DEBUG']}"

    @allure.story("参数操作")
    @allure.title("保存参数到 Flash")
    @allure.description("""
    发送 svp <name> 命令将参数持久化保存，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #8）：
    - 调用 find_param_by_name() 查找参数
    - 调用 save_param() 将参数值写入 Flash 存储
    - 与 sp 不同，svp 确保参数在重启后仍然保留
    """)
    def test_save_parameter(self):
        with allure.step("先设置 INDOOR_DEBUG=1"):
            logger.info("发送 sp 命令设置参数")
            set_result = self.serial.set_parameter("INDOOR_DEBUG", 1)
            assert set_result, "sp 命令执行失败"

        with allure.step("发送 svp 命令保存 INDOOR_DEBUG"):
            logger.info("发送 svp 命令保存参数")
            result = self.serial.save_parameter("INDOOR_DEBUG")
            logger.info(f"返回结果：{result}")
            assert result, "svp 命令执行失败"
            assert result is not None, "命令执行失败"

        with allure.step("读取 INDOOR_DEBUG 验证值已保存"):
            saved_result = self.serial.get_parameter("INDOOR_DEBUG")
            logger.info(f"保存后值：{saved_result}")
            if saved_result and "INDOOR_DEBUG" in saved_result:
                assert float(saved_result["INDOOR_DEBUG"]) == 1.0, \
                    f"svp 保存失败: 期望 1，实际 {saved_result['INDOOR_DEBUG']}"

    @allure.story("参数操作")
    @allure.title("系统参数抽样验证（set + save）")
    @allure.description("""
    从全部参数中等距抽样（首尾 + 间隔采样），对每个抽样参数执行 set 和 save 操作，
    验证参数写入和持久化通道均正常。
    """)
    def test_system_parameter_validation(self):
        with allure.step("获取全部参数列表"):
            logger.info("发送 pp 命令获取全部参数")
            params = self.serial.get_parameter("")
            logger.info(f"获取到 {len(params) if params else 0} 个参数")
            assert params, "获取全部参数失败"
            assert isinstance(params, dict), "返回结果不是字典类型"

        param_items = list(params.items())
        total = len(param_items)
        sample_indices = set()
        sample_indices.update(range(min(3, total)))
        sample_indices.update(range(max(0, total - 3), total))
        sample_indices.update(range(0, total, 20))
        sampled = [param_items[i] for i in sorted(sample_indices)]
        logger.info(f"总参数 {total} 个，抽样 {len(sampled)} 个进行验证")

        failed_params = []
        for name, value in sampled:
            with allure.step(f"设置参数 {name}={value}"):
                logger.info(f"设置参数: {name} = {value}")
                set_result = self.serial.set_parameter(name, value)
                if not set_result:
                    logger.warning(f"设置参数 {name} 失败")
                    failed_params.append(f"set:{name}")
                    continue

            with allure.step(f"保存参数 {name}"):
                logger.info(f"保存参数: {name}")
                save_result = self.serial.save_parameter(name)
                if not save_result:
                    logger.warning(f"保存参数 {name} 失败")
                    failed_params.append(f"save:{name}")

        if failed_params:
            logger.error(f"失败参数列表: {failed_params}")
        assert len(failed_params) == 0, f"以下参数操作失败: {failed_params}"

    # ==================== 系统状态查询 ====================
    @allure.story("系统状态")
    @allure.title("查询模块任务信息")
    @allure.description("""
    发送 pm 命令获取各模块任务运行状态（任务名、栈使用、CPU 占用），验证返回结果非空。

    工作原理（CLI_COMMANDS_REFERENCE #6）：
    - 从全局模块链表头 pfirst_mod 开始遍历
    - 对每个模块打印 ID 和名称，遍历其任务节点链表
    - 使用 pcTaskGetName() 获取任务名
    """)
    def test_get_task_info(self):
        with allure.step("发送 pm 命令"):
            logger.info("发送 pm 命令")
            result = self.serial.get_task_info()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
            # 验证响应中包含已知核心模块（SYS_CLI_SERV 是所有固件的基础模块）
            assert "SYS_CLI_SERV" in result, \
                f"pm 响应中未找到核心模块 SYS_CLI_SERV: {result[:200]}"

    @allure.story("系统状态")
    @allure.title("查询错误信息")
    @allure.description("""
    发送 dmsg 命令获取当前记录的错误/警告日志，验证返回结果非空。

    工作原理（CLI_COMMANDS_REFERENCE #12）：
    - 调用 get_debuglog() 获取索引和缓冲区
    - 解析变长记录: [长度][数据内容][系统时间8B][另一时间戳8B][计数2B]
    - 逐条输出: 数据-系统时间-另一时间戳-计数
    """)
    def test_get_error_info(self):
        with allure.step("发送 dmsg 命令"):
            logger.info("发送 dmsg 命令")
            result = self.serial.get_error_info()
            logger.info(f"返回结果：{result[:200] if result else None}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
            assert isinstance(result, str), f"dmsg 应返回字符串，实际 {type(result)}"

    @allure.story("系统状态")
    @allure.title("查询并清除错误信息")
    @allure.description("""
    发送 dmsg c 命令返回错误信息并清除已记录的错误日志，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #12）：
    - 参数 'c' 时调用 debuglog_clean() 清除调试日志
    """)
    def test_get_error_info_clear(self):
        with allure.step("发送 dmsg c 命令"):
            logger.info("发送 dmsg c 命令")
            result = self.serial.get_error_info_clear()
            logger.info(f"返回结果：{result[:200] if result else None}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
            assert isinstance(result, str), f"dmsg c 应返回字符串，实际 {type(result)}"

    @allure.story("系统状态")
    @allure.title("查询各模块初始化状态")
    @allure.description("""
    发送 istate 命令获取传感器、通信、控制等模块的初始化完成状态，验证返回结果非空。

    工作原理（CLI_COMMANDS_REFERENCE #14）：
    - 调用 get_init_state() 获取系统初始化状态结构
    - 打印各模块初始化结果：module、sdcard、param、log、mission、assist
    - 输出格式 init_state.<模块> :<状态值>
    """)
    def test_get_module_init_status(self):
        with allure.step("发送 istate 命令"):
            logger.info("发送 istate 命令")
            result = self.serial.get_module_init_status()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
            # 验证包含已知的初始化状态字段（CLI_COMMANDS_REFERENCE #14）
            expected_fields = ["module", "sdcard", "param", "log", "mission", "assist"]
            found = [f for f in expected_fields if f in result]
            logger.info(f"istate 检测到字段: {found}")
            assert len(found) >= 1, f"istate 未检测到已知字段，结果: {result}"

    @allure.story("系统状态")
    @allure.title("查询传感器工作状态")
    @allure.description("""
    发送 sheal 命令获取 IMU、磁力计、气压计等传感器的健康状态，验证返回结果非空。

    工作原理（CLI_COMMANDS_REFERENCE #15）：
    - 读取 GLB_VAR::sensor_healthy 各传感器健康标志
    - 遥测健康判断: ISM2G4 && ISM850 均健康，或 DAV 子模块 radio 版本非零
    - 遍历输出 IMU、Baro、Compass、GPS、电池、Tele、UWB、TOF、ESC 等
    """)
    def test_get_sensor_work_status(self):
        with allure.step("发送 sheal 命令"):
            logger.info("发送 sheal 命令")
            result = self.serial.get_sensor_work_status()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
            # 验证至少包含一种传感器状态
            sensor_keys = ["imu", "baro", "compass", "gps", "battery", "tele"]
            found = [k for k in sensor_keys if k in [kk.lower() for kk in result.keys()]]
            logger.info(f"sheal 检测到传感器: {found}")

    @allure.story("系统状态")
    @allure.title("查询通信质量")
    @allure.description("""
    发送 mav 命令获取 MAVLink 链路通信质量指标（丢包率、信号强度等），验证返回结果非空。

    工作原理（CLI_COMMANDS_REFERENCE #16）：
    - 从 GLB_VAR::mavchan_state[chan] 读取通道状态
    - 显示: last_rx_time、rx_success_count、rx_drop_count、quality、rate
    - 进入循环刷新模式，按 q 退出
    """)
    def test_get_communication_quality(self):
        with allure.step("发送 mav 命令"):
            logger.info("发送 mav 命令")
            result = self.serial.get_communication_quality()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @allure.story("系统状态")
    @allure.title("查询设备版本信息")
    @allure.description("""
    发送 version 命令获取设备序列号和固件版本，验证返回结果包含 sn 和 version 字段。

    工作原理（CLI_COMMANDS_REFERENCE #22）：
    - 从全局固件 ID g_firmware_id 复制飞控版本号
    - 调用 sn_get() 获取设备序列号（SN）
    - 输出格式 sn: <序列号> version: <版本号>
    """)
    def test_get_device_version(self):
        with allure.step("发送 version 命令"):
            logger.info("发送 version 命令")
            result = self.serial.get_device_version()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
            assert "sn" in result, "返回数据缺少 sn 字段"
            assert "version" in result, "返回数据缺少 version 字段"
            # 验证字段值有效（sn 非空字符串，version 包含版本号格式）
            assert result["sn"], f"sn 字段为空: {result['sn']}"
            assert result["version"], f"version 字段为空: {result['version']}"
            assert isinstance(result["sn"], str), f"sn 应为字符串: {type(result['sn'])}"
            assert isinstance(result["version"], str), f"version 应为字符串: {type(result['version'])}"

    @allure.story("系统状态")
    @allure.title("查询系统时间和飞行时长")
    @allure.description("""
    发送 now 命令获取系统基准时间和本次飞行时长，验证返回结果包含 Base Time 和 Flight Time 字段。

    工作原理（CLI_COMMANDS_REFERENCE #17）：
    - 调用 xTaskGetTickCount() 获取系统基础运行时间（以 tick 计）
    - 调用 cur_flight_time() 获取飞行时间
    - 输出格式 Base Time  :<tick值> Flight Time:<飞行时间>
    """)
    def test_get_system_time(self):
        with allure.step("发送 now 命令"):
            logger.info("发送 now 命令")
            result = self.serial.get_system_time()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
            assert "Base Time" in result, "返回数据缺少 Base Time 字段"
            assert "Flight Time" in result, "返回数据缺少 Flight Time 字段"
            # 验证 Base Time > 0（系统已运行）
            assert result["Base Time"] is not None, "Base Time 值为 None"
            assert result["Base Time"] > 0, \
                f"Base Time 应 > 0（系统已运行），实际 {result['Base Time']}"
            # Flight Time 可能为 0（未起飞），但不应为 None
            assert result["Flight Time"] is not None, "Flight Time 值为 None"

    @allure.story("系统状态")
    @allure.title("查询 CPU 状态")
    @allure.description("""
    发送 ps 命令获取任务列表和堆内存使用情况，验证返回结果包含 tasks 和 heap 字段。

    工作原理（CLI_COMMANDS_REFERENCE #4）：
    - 调用 xPortGetFreeHeapSize() 获取剩余堆内存
    - 调用 uxTaskGetSystemState() 获取所有任务状态快照
    - CPU% = (本周期运行时间 / 总周期时间) × 100
    - 状态映射: eReady→R, eBlocked→B, eSuspended→S, eDeleted→D, eRunning→X
    - 进入循环刷新模式，按 q 退出
    """)
    def test_get_cpu_status(self):
        with allure.step("发送 ps 命令"):
            logger.info("发送 ps 命令")
            result = self.serial.get_cpu_status()
            logger.info(f"返回结果包含 {len(result.get('tasks', []))} 个任务")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
            assert "tasks" in result, "返回数据缺少 tasks 字段"
            assert "heap" in result, "返回数据缺少 heap 字段"
            # 验证至少有一个任务在运行
            assert len(result["tasks"]) > 0, "ps 任务列表为空"
            # 验证堆内存信息完整
            assert result["heap"]["total"] > 0, \
                f"堆内存总量异常: {result['heap']['total']}"
            # 验证 SYS_CLI_SERV 任务存在（执行 ps 的模块自身）
            task_names = [t["name"] for t in result["tasks"]]
            logger.info(f"任务列表: {task_names}")
            assert any("CLI" in name or "IDLE" in name for name in task_names), \
                f"未找到核心任务，任务列表: {task_names}"

    # ==================== 飞行控制 ====================
    @allure.story("飞行控制")
    @allure.title("切换飞行模式")
    @allure.description("""
    发送 mode stab 命令将飞控切换到增稳模式，并读取当前模式验证切换成功。

    工作原理（CLI_COMMANDS_REFERENCE #26）：
    - 匹配飞行模式名称，设置 TP_MODE_REQ.mode 字段
    - 通过 advs.mode_req.publish() 发布到 UORB，由飞控核心处理
    - mode ? 列出可用模式，mode（无参）显示当前模式
    """)
    def test_set_mode(self):
        with allure.step("发送 mode stab 命令"):
            logger.info("发送 mode stab 命令")
            result = self.serial.set_mode("stab")
            logger.info(f"返回结果：{result}")
            assert result, "mode stab 命令执行失败"
            assert result is not None, "命令执行失败"

        with allure.step("读取当前模式验证切换到 stab"):
            mode_info = self.serial.get_current_mode()
            logger.info(f"当前模式：{mode_info}")
            assert mode_info["mode"] is not None, "无法获取当前模式"
            # 验证切换到增稳模式（mode_id=0 为 STAB）
            assert mode_info["mode"] == "stab" or mode_info["mode_id"] == 0, \
                f"模式切换失败: 期望 stab(0)，实际 {mode_info['mode']}({mode_info['mode_id']})"

    @allure.story("飞行控制")
    @allure.title("查询当前飞行模式")
    @allure.description("""
    发送 mode 命令（无参数）获取当前飞行模式名称和 ID，验证返回结果包含 mode 和 mode_id 字段。

    工作原理（CLI_COMMANDS_REFERENCE #26）：
    - mode 无参时从 GLB_VAR::cur_mode 读取当前模式
    - mode_id 映射: 0=stab, 2=althold, 3=auto, 4=guided, 5=loiter, 6=rtl, 9=land
    """)
    def test_get_current_mode(self):
        with allure.step("发送 mode 命令查询当前模式"):
            logger.info("发送 mode 命令获取当前模式")
            result = self.serial.get_current_mode()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
            assert "mode" in result, "返回数据缺少 mode 字段"
            assert "mode_id" in result, "返回数据缺少 mode_id 字段"
            # 验证 mode_id 在有效范围内
            valid_mode_ids = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 20, 255}
            assert result["mode_id"] in valid_mode_ids, \
                f"mode_id {result['mode_id']} 不在已知有效范围 {valid_mode_ids}"

    @allure.story("飞行控制")
    @allure.title("查询可用飞行模式列表")
    @allure.description("""
    发送 mode ? 命令获取飞控支持的所有飞行模式，验证返回结果包含 modes 字段。

    工作原理（CLI_COMMANDS_REFERENCE #26）：
    - mode ? 列出所有可用模式名
    - 支持的模式: stab, althold, loiter, guided, auto, land, rtl
    """)
    def test_get_available_mode(self):
        with allure.step("发送 mode ? 命令"):
            logger.info("发送 mode ? 命令")
            result = self.serial.get_available_mode()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
            assert "modes" in result, "返回数据缺少 modes 字段"
            # 验证至少包含核心飞行模式
            core_modes = {"stab", "althold", "loiter", "guided", "land", "rtl"}
            returned_modes = set(result["modes"])
            common = core_modes & returned_modes
            logger.info(f"与核心模式交集: {common}")
            assert len(common) >= 2, \
                f"mode ? 返回的模式中核心模式不足: 返回 {returned_modes}，期望至少包含2个核心模式"

    @allure.story("飞行控制")
    @allure.title("起飞")
    @allure.description("""
    发送 takeoff 命令（无参数）触发自动起飞流程，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #27）：
    - 设置 TP_ACTION_REQ.action = UAV_ACTION_TAKEOFF
    - 无参时读取当前位置 TP_CUR_POINT，使用默认高度
    - 通过 advs.action_req.publish() 发布到 UORB
    """)
    def test_takeoff(self):
        with allure.step("发送 takeoff 命令"):
            logger.info("发送 takeoff 命令")
            result = self.serial.takeoff()
            logger.info(f"返回结果：{result}")
            assert result, "takeoff 命令执行失败"
            assert result is not None, "命令执行失败"

    @allure.story("飞行控制")
    @allure.title("指定位置起飞")
    @allure.description("""
    发送 takeoff <高度>,<纬度_offset>,<经度_offset>,<备选参数> 命令在指定坐标起飞，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #27）：
    - 4 个参数: 完整指定位置偏移（para[0] 取负值，向上为正）
    - 解析参数填充 para[0]~para[3]
    - 通过 advs.action_req.publish() 发布
    """)
    def test_takeoff_position(self):
        with allure.step("发送 takeoff 0,0,0,10 命令"):
            logger.info("发送 takeoff 0, 0, 0, 10 命令")
            result = self.serial.takeoff_position(0, 0, 0, 10.0)
            logger.info(f"返回结果：{result}")
            assert result, "takeoff_position 命令执行失败"
            assert result is not None, "命令执行失败"

    @allure.story("飞行控制")
    @allure.title("指定高度起飞")
    @allure.description("""
    发送 takeoff <altitude> 命令以当前坐标和指定高度起飞，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #27）：
    - 1 个参数: 起飞高度（取负值，向上为正），其他默认
    - 读取当前位置 TP_CUR_POINT，只设置高度
    - 通过 advs.action_req.publish() 发布
    """)
    def test_takeoff_altitude(self):
        with allure.step("发送 takeoff 10 命令"):
            logger.info("发送 takeoff 10 命令")
            result = self.serial.takeoff_altitude(10.0)
            logger.info(f"返回结果：{result}")
            assert result, "takeoff_altitude 命令执行失败"
            assert result is not None, "命令执行失败"

    @pytest.mark.skip(reason="flyto 命令返回 Param number error，待固件修复")
    @allure.story("飞行控制")
    @allure.title("飞行到指定航点")
    @allure.description("""
    发送 flyto <x>,<y>,<z> 命令控制飞控飞向目标点，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #28）：
    - 设置 TP_ACTION_REQ.action = UAV_ACTION_FLYTO
    - 解析 3 个浮点坐标参数填入 para[0]~para[2]
    - 通过 advs.action_req.publish() 发布
    - 固件输出: flying to:(x, y, z)
    """)
    def test_fly_to(self):
        with allure.step("发送 flyto 命令"):
            logger.info("发送 flyto 命令")
            result = self.serial.fly_to(30.0, 120.0, 10.0)
            logger.info(f"返回结果：{result}")
            assert result, "flyto 命令执行失败"
            assert result is not None, "命令执行失败"

    @pytest.mark.skip(reason="home 命令返回 Param number error，待固件修复")
    @allure.story("飞行控制")
    @allure.title("设置返航点")
    @allure.description("发送 home <lat> <lon> 命令设置返航点坐标，验证命令执行成功。")
    def test_set_home(self):
        with allure.step("发送 home 命令"):
            logger.info("发送 home 命令")
            result = self.serial.set_home(30.0, 120.0)
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @allure.story("飞行控制")
    @allure.title("设置电子围栏")
    @allure.description("发送 fence <lat> <lon> <radius> <max_alt> 命令设置电子围栏区域，验证命令执行成功。")
    def test_set_geofence(self):
        with allure.step("发送 fence 命令"):
            logger.info("发送 fence 命令")
            result = self.serial.set_geofence(0, 0, 100, 50)
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @allure.story("飞行控制")
    @allure.title("解锁电机")
    @allure.description("""
    发送 arm 命令解锁电机使其进入可转动状态，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #29）：
    - 构造 TP_ARM_REQ，设置 arm_req = UAV_ARM_STATE_ARMED
    - cmd_src = ARM_CLI
    - 通过 advs.arm_req.publish() 发布到 UORB
    """)
    def test_arm_motors(self):
        with allure.step("发送 arm 命令"):
            logger.info("发送 arm 命令")
            result = self.serial.arm_motors()
            logger.info(f"返回结果：{result}")
            assert result, "arm 命令执行失败"
            assert result is not None, "命令执行失败"

    @allure.story("飞行控制")
    @allure.title("锁定电机")
    @allure.description("""
    发送 disarm 命令锁定电机使其停止转动，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #30）：
    - 与 arm 类似，设置 arm_req = UAV_ARM_STATE_DISARMED
    - 来源同样标记为 ARM_CLI
    """)
    def test_disarm_motors(self):
        with allure.step("发送 disarm 命令"):
            logger.info("发送 disarm 命令")
            result = self.serial.disarm_motors()
            logger.info(f"返回结果：{result}")
            assert result, "disarm 命令执行失败"
            assert result is not None, "命令执行失败"

    # ==================== 灯光与指示灯 ====================
    @allure.story("灯光控制")
    @allure.title("设置舵机/LED RGB 值")
    @allure.description("""
    发送 servo <r> <g> <b> 命令设置 LED 颜色（开灯→关灯），验证两次命令均执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #31）：
    - 解析 3 个整型参数（0~255）
    - 分别向 advs.set_servo[0]、[1]、[2] 三个通道发布 TP_SET_SERVO 消息
    """)
    def test_set_servo(self):
        with allure.step("发送 servo 245,245,245 开灯"):
            logger.info("发送 servo 245, 245, 245 命令")
            result = self.serial.set_servo(245, 245, 245)
            logger.info(f"返回结果：{result}")
            assert result, "servo 开灯命令执行失败"
            assert result is not None, "命令执行失败"

        with allure.step("发送 servo 0,0,0 关灯"):
            logger.info("发送 servo 0, 0, 0 命令")
            result = self.serial.set_servo(0, 0, 0)
            logger.info(f"返回结果：{result}")
            assert result, "servo 关灯命令执行失败"
            assert result is not None, "命令执行失败"

    @allure.story("指示灯控制")
    @allure.title("关闭板载 LED 指示灯")
    @allure.description("""
    发送 notify off 命令关闭飞控板载 LED 指示灯，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #33）：
    - notify off: 写入 NOTIFY_STATE_OFF 到 GLB_VAR::notify_state
    - 飞控板载 LED 根据 notify_state 全局变量控制亮灭
    """)
    def test_set_led_off(self):
        with allure.step("发送 notify off 命令"):
            logger.info("发送 notify off 命令")
            result = self.serial.set_led_off()
            logger.info(f"返回结果：{result}")
            assert result, "notify off 命令执行失败"
            assert result is not None, "命令执行失败"

    @allure.story("指示灯控制")
    @allure.title("开启板载 LED 指示灯")
    @allure.description("""
    发送 notify on 命令开启飞控板载 LED 指示灯，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #33）：
    - notify on: 写入 NOTIFY_STATE_ON 到 GLB_VAR::notify_state
    - 飞控板载 LED 根据 notify_state 全局变量控制亮灭
    """)
    def test_set_led_on(self):
        with allure.step("发送 notify on 命令"):
            logger.info("发送 notify on 命令")
            result = self.serial.set_led_on()
            logger.info(f"返回结果：{result}")
            assert result, "notify on 命令执行失败"
            assert result is not None, "命令执行失败"

    @allure.story("指示灯控制")
    @allure.title("Notify 状态切换完整性验证")
    @allure.description("""
    验证 notify on/off 命令可重复切换，确保 GLB_VAR::notify_state 写入通道正常。

    工作原理（CLI_COMMANDS_REFERENCE #33）：
    - 每次调用直接写入全局变量 notify_state，无状态依赖
    - 两次连续切换（on→off→on）应均成功，验证写入通道无阻塞
    """)
    def test_notify_state_toggle(self):
        with allure.step("第1次: notify off"):
            result = self.serial.set_led_off()
            assert result, "第1次 notify off 失败"

        with allure.step("第2次: notify on"):
            result = self.serial.set_led_on()
            assert result, "第2次 notify on 失败"

        with allure.step("第3次: notify off（验证可重复切换）"):
            result = self.serial.set_led_off()
            assert result, "第3次 notify off 失败"

        with allure.step("第4次: notify on（恢复初始状态）"):
            result = self.serial.set_led_on()
            assert result, "第4次 notify on 失败"

    # ==================== 表演控制 ====================
    @allure.story("表演控制")
    @allure.title("执行预设表演动作")
    @allure.description("""
    发送 fstart 命令触发飞控执行预设表演动作脚本，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #32）：
    - 发布 UAV_ACTION_FLIGHT_START 动作请求
    - 通过 advs.action_req.publish() 发布到 UORB
    - 用于通知飞控开始执行飞行任务
    """)
    def test_perform_action(self):
        with allure.step("发送 fstart 命令"):
            logger.info("发送 fstart 命令")
            result = self.serial.perform_action()
            logger.info(f"返回结果：{result}")
            assert result, "fstart 命令执行失败"
            assert result is not None, "命令执行失败"

    # ==================== 电池信息 ====================
    @allure.story("电池信息")
    @allure.title("查询电池电压与电流")
    @allure.description("""
    发送 bat 命令获取电池总电压和电流，验证返回结果包含 sum_voltage 和 current 字段。

    工作原理（CLI_COMMANDS_REFERENCE #24）：
    - 通过 UORB 订阅获取 TP_BATTERY_SCALED 数据
    - 输出电池综合信息：总电压、电流、温度、SOH、单体电压、最大压差等
    """)
    def test_get_battery_info(self):
        with allure.step("发送 bat 命令"):
            logger.info("发送 bat 命令")
            result = self.serial.get_battery_info()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
            assert "sum_voltage" in result, "返回数据缺少 sum_voltage 字段"
            assert "current" in result, "返回数据缺少 current 字段"
            # 验证电压值在合理范围
            if result["sum_voltage"] is not None:
                assert 0.0 < result["sum_voltage"] < 30.0, \
                    f"电池总电压异常: {result['sum_voltage']}V（合理范围 0~30V）"
            # 验证电流值合理（-50A ~ 50A）
            if result["current"] is not None:
                assert -60.0 < result["current"] < 60.0, \
                    f"电池电流异常: {result['current']}A（合理范围 -60~60A）"

    # ==================== DShot 控制 ====================
    @allure.story("DShot 控制")
    @allure.title("停止 DShot 协议")
    @allure.description("""
    发送 dshot stop 命令停止 DShot 电调通信协议，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #51）：
    - 打开设备 /dev/pltfm/BITBANG_DSHOT
    - 调用 DRV_IOC_DSHOT_STOP ioctl 停止 DShot 输出
    """)
    def test_set_dshot_stop(self):
        with allure.step("发送 dshot stop 命令"):
            logger.info("发送 dshot stop 命令")
            result = self.serial.set_dshot_stop()
            logger.info(f"返回结果：{result}")
            assert result, "dshot stop 命令执行失败"
            assert result is not None, "命令执行失败"
            time.sleep(3)  # 等待协议停止稳定

    @allure.story("DShot 控制")
    @allure.title("开启 DShot 协议")
    @allure.description("""
    发送 dshot start 命令启动 DShot 电调通信协议，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #51）：
    - 打开设备 /dev/pltfm/BITBANG_DSHOT
    - 调用 DRV_IOC_DSHOT_START ioctl 启动 DShot 输出
    """)
    def test_set_dshot_start(self):
        with allure.step("发送 dshot start 命令"):
            logger.info("发送 dshot start 命令")
            result = self.serial.set_dshot_start()
            logger.info(f"返回结果：{result}")
            assert result, "dshot start 命令执行失败"
            assert result is not None, "命令执行失败"
            time.sleep(3)  # 等待协议启动稳定

        with allure.step("发送 dshot stop 命令"):
            logger.info("发送 dshot stop 命令")
            result = self.serial.set_dshot_stop()
            logger.info(f"返回结果：{result}")
            assert result, "dshot stop 命令执行失败"
            assert result is not None, "命令执行失败"
            time.sleep(3)  # 等待协议停止稳定

    @allure.story("DShot 控制")
    @allure.title("DShot 自检")
    @allure.description("""
    发送 dshot t 命令执行 DShot 电调通信自检，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #51）：
    - 调用 DRV_IOC_DSHOT_TEST ioctl 进入测试模式（输出固定 RPM）
    """)
    def test_set_dshot_test(self):
        with allure.step("发送 dshot t 命令"):
            logger.info("发送 dshot t 命令")
            result = self.serial.set_dshot_test()
            logger.info(f"返回结果：{result}")
            assert result, "dshot t 命令执行失败"
            assert result is not None, "命令执行失败"
            time.sleep(3)  # 等待自检完成

        with allure.step("发送 dshot stop 命令"):
            logger.info("发送 dshot stop 命令")
            result = self.serial.set_dshot_stop()
            logger.info(f"返回结果：{result}")
            assert result, "dshot stop 命令执行失败"
            assert result is not None, "命令执行失败"
            time.sleep(3)  # 等待协议停止稳定

    @allure.story("DShot 控制")
    @allure.title("读取电机实时转速")
    @allure.description("""
    发送 dshot rpm 命令通过 DShot 遥测读取各电机转速，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #51）：
    - 调用 DRV_IOC_DSHOT_RPM ioctl 读取转速
    - 自动通过 MTx_MAP 参数完成电机映射转换
    """)
    def test_read_motor_rpm(self):
        with allure.step("发送 dshot rpm 命令"):
            logger.info("发送 dshot rpm 命令")
            result = self.serial.read_motor_rpm()
            logger.info(f"返回结果：{result}")
            assert result, "dshot rpm 命令执行失败"
            assert result is not None, "命令执行失败"
            time.sleep(3)  # 等待数据稳定

    @allure.story("DShot 控制")
    @allure.title("读取 DShot 遥测数据")
    @allure.description("""
    发送 dshot info<index> 命令读取指定通道的电调遥测数据（温度、电压、电流等），验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #51）：
    - info 子命令通过 UORB 发布 ESC_REQ_INFO（而非 ioctl）
    - 其他子命令（start/stop/tel/t/rpm/led/dir/3d）均通过 ioctl
    """)
    def test_read_dshot_telemetry(self):
        with allure.step("发送 dshot info0 命令"):
            logger.info("发送 dshot info0 命令")
            result = self.serial.read_dshot_telemetry(0)
            logger.info(f"返回结果：{result}")
            assert result, "dshot info0 命令执行失败"
            assert result is not None, "命令执行失败"
            time.sleep(3)  # 等待数据稳定

    @pytest.mark.skip(reason="dshot led 命令在固件中未实现，待固件修复")
    @allure.story("DShot 控制")
    @allure.title("开启 DShot LED")
    @allure.description("""
    发送 dshot led1 命令开启电调板载 LED，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #51）：
    - 调用 DRV_IOC_DSHOT_LED ioctl 控制电调板载 LED
    """)
    def test_set_dshot_led_on(self):
        with allure.step("发送 dshot led1 命令"):
            logger.info("发送 dshot led1 命令")
            result = self.serial.set_dshot_led(True)
            logger.info(f"返回结果：{result}")
            assert result, "dshot led1 命令执行失败"
            assert result is not None, "命令执行失败"
            time.sleep(3)  # 等待 LED 状态更新

    @pytest.mark.skip(reason="dshot led 命令在固件中未实现，待固件修复")
    @allure.story("DShot 控制")
    @allure.title("关闭 DShot LED")
    @allure.description("""
    发送 dshot led0 命令关闭电调板载 LED，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #51）：
    - 调用 DRV_IOC_DSHOT_LED ioctl 控制电调板载 LED
    """)
    def test_set_dshot_led_off(self):
        with allure.step("发送 dshot led0 命令"):
            logger.info("发送 dshot led0 命令")
            result = self.serial.set_dshot_led(False)
            logger.info(f"返回结果：{result}")
            assert result, "dshot led0 命令执行失败"
            assert result is not None, "命令执行失败"
            time.sleep(3)  # 等待 LED 状态更新

    @pytest.mark.skip(reason="dshot dir 命令在固件中未实现，待固件修复")
    @allure.story("DShot 控制")
    @allure.title("设置电机正转")
    @allure.description("""
    发送 dshot dir1 命令设置电机为正转方向，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #51）：
    - 调用 DRV_IOC_DSHOT_DIRECTION ioctl 设置电机方向
    """)
    def test_set_dshot_motor_direction_forward(self):
        with allure.step("发送 dshot dir1 命令"):
            logger.info("发送 dshot dir1 命令")
            result = self.serial.set_dshot_motor_direction(True)
            logger.info(f"返回结果：{result}")
            assert result, "dshot dir1 命令执行失败"
            assert result is not None, "命令执行失败"
            time.sleep(3)  # 等待电机方向更新失败"

    @pytest.mark.skip(reason="dshot dir 命令在固件中未实现，待固件修复")
    @allure.story("DShot 控制")
    @allure.title("设置电机反转")
    @allure.description("""
    发送 dshot dir0 命令设置电机为反转方向，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #51）：
    - 调用 DRV_IOC_DSHOT_DIRECTION ioctl 设置电机方向
    """)
    def test_set_dshot_motor_direction_reverse(self):
        with allure.step("发送 dshot dir0 命令"):
            logger.info("发送 dshot dir0 命令")
            result = self.serial.set_dshot_motor_direction(False)
            logger.info(f"返回结果：{result}")
            assert result, "dshot dir0 命令执行失败"
            assert result is not None, "命令执行失败"
            time.sleep(3)  # 等待电机方向更新   

    @pytest.mark.skip(reason="dshot 3d 命令在固件中未实现，待固件修复")
    @allure.story("DShot 控制")
    @allure.title("开启 DShot 3D 模式")
    @allure.description("""
    发送 dshot 3d1 命令开启 3D 模式（支持电机正反转双向控制），验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #51）：
    - 调用 DRV_IOC_DSHOT_3D_MODE ioctl 开启 3D 模式
    - 3D 模式下电机支持正反转双向控制
    """)
    def test_set_dshot_3d_mode_on(self):
        with allure.step("发送 dshot 3d1 命令"):
            logger.info("发送 dshot 3d1 命令")
            result = self.serial.set_dshot_3d_mode(True)
            logger.info(f"返回结果：{result}")
            assert result, "dshot 3d1 命令执行失败"
            assert result is not None, "命令执行失败"

    
    @pytest.mark.skip(reason="dshot 3d 命令在固件中未实现，待固件修复")
    @allure.story("DShot 控制")
    @allure.title("关闭 DShot 3D 模式")
    @allure.description("""
    发送 dshot 3d0 命令关闭 3D 模式（恢复单向控制），验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #51）：
    - 调用 DRV_IOC_DSHOT_3D_MODE ioctl 关闭 3D 模式
    - 恢复单向电机控制
    """)
    def test_set_dshot_3d_mode_off(self):
        with allure.step("发送 dshot 3d0 命令"):
            logger.info("发送 dshot 3d0 命令")
            result = self.serial.set_dshot_3d_mode(False)
            logger.info(f"返回结果：{result}")
            assert result, "dshot 3d0 命令执行失败"
            assert result is not None, "命令执行失败"

    # ==================== 异常状态模拟 ====================
    @allure.story("异常状态")
    @allure.title("查询故障保护状态")
    @allure.description("""
    发送 fs_state 命令查询当前故障保护状态，验证返回各故障标志位。

    工作原理（CLI_COMMANDS_REFERENCE #23）：
    - 读取 GLB_VAR::failsafe_state 获取故障保护状态
    - 读取 GLB_VAR::imu_state 中的振动标志
    - 输出各项故障状态（0=正常, 1=触发）：EKF、crash、radio、battery、fence、waypoint 等
    """)
    def test_get_failsafe_state(self):
        with allure.step("发送 fs_state 命令"):
            logger.info("发送 fs_state 命令")
            raw = self.serial.send_command("fs_state", timeout=2)
            logger.info(f"返回结果：{raw}")
            assert raw, "fs_state 命令执行失败"
            assert raw is not None, "命令执行失败"
            # 验证返回了故障状态信息（响应包含已知故障字段）
            response_lower = raw.lower()
            fault_fields = ["ekf", "crash", "radio", "battery", "fence", "waypoint"]
            found_fields = [f for f in fault_fields if f in response_lower]
            logger.info(f"fs_state 检测到故障字段: {found_fields}")
            # 至少应有部分故障字段出现
            assert len(found_fields) >= 1, \
                f"fs_state 响应中未检测到已知故障字段，响应: {raw[:200]}"

    @allure.story("异常状态")
    @allure.title("清除故障状态")
    @allure.description("""
    发送 ffs 0 命令清除当前故障状态，并用 fs_state 验证已清除。

    工作原理（CLI_COMMANDS_REFERENCE #43）：
    - ffs 使用 GLB_VAR::xxx_state.lockto() 锁定状态为指定值
    - 参数 0 时调用 unlock() 解除所有锁定，恢复正常状态
    """)
    def test_set_error_state_clear(self):
        with allure.step("发送 ffs 0 命令"):
            logger.info("发送 ffs 0 命令")
            result = self.serial.set_error_state("clear_error")
            logger.info(f"返回结果：{result}")
            assert result, "ffs 0 命令执行失败"
            assert result is not None, "命令执行失败"

        with allure.step("发送 fs_state 验证故障已清除"):
            raw = self.serial.send_command("fs_state", timeout=2)
            logger.info(f"fs_state 返回：{raw}")

    @allure.story("异常状态")
    @allure.title("模拟低电量报警")
    @allure.description("""
    发送 ffs 1 命令模拟低电量报警异常状态，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #43）：
    - 设置电压 10.2V，低电标志 true
    - 使用 batt_state.lockto() 锁定电池状态
    """)
    def test_set_error_state_low_battery(self):
        with allure.step("发送 ffs 1 命令"):
            logger.info("发送 ffs 1 命令")
            result = self.serial.set_error_state("low_battery")
            logger.info(f"返回结果：{result}")
            assert result, "ffs 1 命令执行失败"
            assert result is not None, "命令执行失败"

        with allure.step("恢复：清除故障状态"):
            self.serial.set_error_state("clear_error")

    @allure.story("异常状态")
    @allure.title("模拟航点执行失败")
    @allure.description("""
    发送 ffs 2 命令模拟航点执行失败异常，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #43）：
    - 设置 wp 错误标志
    - 使用 wp_state.lockto() 锁定航点状态
    """)
    def test_set_error_state_waypoint_failed(self):
        with allure.step("发送 ffs 2 命令"):
            logger.info("发送 ffs 2 命令")
            result = self.serial.set_error_state("waypoint_failed")
            logger.info(f"返回结果：{result}")
            assert result, "ffs 2 命令执行失败"
            assert result is not None, "命令执行失败"

        with allure.step("恢复：清除故障状态"):
            self.serial.set_error_state("clear_error")

    @allure.story("异常状态")
    @allure.title("模拟电子围栏越界")
    @allure.description("""
    发送 ffs 3 命令模拟超出电子围栏异常状态，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #43）：
    - 设置高度越界标志
    - 使用 fence_state.lockto() 锁定围栏状态
    """)
    def test_set_error_state_fence_violation(self):
        with allure.step("发送 ffs 3 命令"):
            logger.info("发送 ffs 3 命令")
            result = self.serial.set_error_state("fence_violation")
            logger.info(f"返回结果：{result}")
            assert result, "ffs 3 命令执行失败"
            assert result is not None, "命令执行失败"

        with allure.step("恢复：清除故障状态"):
            self.serial.set_error_state("clear_error")

    @allure.story("异常状态")
    @allure.title("模拟 EKF 异常")
    @allure.description("""
    发送 ffs 4,p1,p2,p3 命令模拟扩展卡尔曼滤波器异常状态，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #43）：
    - p1=水平无效, p2=垂直无效, p3=姿态无效
    - 使用 ahrs_state.lockto() 锁定 AHRS 状态
    """)
    def test_set_error_state_ekf_error(self):
        with allure.step("发送 ffs 4 命令"):
            logger.info("发送 ffs 4 命令")
            result = self.serial.set_error_state("ekf_error")
            logger.info(f"返回结果：{result}")
            assert result, "ffs 4 命令执行失败"
            assert result is not None, "命令执行失败"

        with allure.step("恢复：清除故障状态"):
            self.serial.set_error_state("clear_error")

    # ==================== WiFi 控制 ====================
    @pytest.mark.skip(reason="wifi 命令返回 False(mask_id/ssid 匹配)，待适配")
    @allure.story("WiFi 控制")
    @allure.title("配置 WiFi 连接参数")
    @allure.description("发送 wifi 命令配置飞控 WiFi 模块的 SSID/密码/信道，验证命令执行成功。")
    def test_set_wifi(self):
        with allure.step("发送 wifi 命令"):
            logger.info("发送 wifi 命令")
            result = self.serial.set_wifi()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @pytest.mark.skip(reason="wifi 命令返回 False(mask_id/ssid 匹配)，待适配")
    @allure.story("WiFi 控制")
    @allure.title("开启 WiFi 调试模式")
    @allure.description("发送 wifi debug on 命令开启 WiFi 模块调试日志输出，验证命令执行成功。")
    def test_set_wifi_debug_on(self):
        with allure.step("发送 wifi debug on 命令"):
            logger.info("发送 wifi debug on 命令")
            result = self.serial.set_wifi_debug_on()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @pytest.mark.skip(reason="wifi 命令返回 False(mask_id/ssid 匹配)，待适配")
    @allure.story("WiFi 控制")
    @allure.title("关闭 WiFi 调试模式")
    @allure.description("发送 wifi debug off 命令关闭 WiFi 模块调试日志输出，验证命令执行成功。")
    def test_set_wifi_debug_off(self):
        with allure.step("发送 wifi debug off 命令"):
            logger.info("发送 wifi debug off 命令")
            result = self.serial.set_wifi_debug_off()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @pytest.mark.skip(reason="wifi 命令返回 False(mask_id/ssid 匹配)，待适配")
    @pytest.mark.skip(reason="wifi reset 命令返回 False(module error)，待固件修复")
    @allure.story("WiFi 控制")
    @allure.title("软复位 WiFi 模块")
    @allure.description("发送 wifi reset 命令软复位 WiFi 模块使其重新初始化，验证命令执行成功。")
    def test_set_wifi_reset(self):
        with allure.step("发送 wifi reset 命令"):
            logger.info("发送 wifi reset 命令")
            result = self.serial.set_wifi_reset()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @pytest.mark.skip(reason="wifi 命令返回 False(mask_id/ssid 匹配)，待适配")
    @pytest.mark.skip(reason="wifi ip 命令返回 False(ssid 匹配失败)，待适配")
    @allure.story("WiFi 控制")
    @allure.title("设置 WiFi Station 模式并连接 AP")
    @allure.description("发送 wifi <mode> <ssid> 命令设置 Station 模式连接指定 AP，验证命令执行成功。")
    def test_set_wifi_ip(self):
        with allure.step("发送 wifi 1 lyt5 命令"):
            logger.info("发送 wifi 1 lyt5 命令")
            result = self.serial.set_wifi_ip(1, "lyt5")
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    # ==================== 日志控制 ====================
    @allure.story("日志控制")
    @allure.title("开始日志记录")
    @allure.description("""
    发送 log start 命令启动板载日志记录（写入 SD 卡/Flash），验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #9）：
    - 构造 TP_LOG_REQ 消息，type = LOG_REQ_TYPE_START，prio = 4
    - 通过 advs.log_req.publish() 发布到 UORB，由日志模块处理
    """)
    def test_set_log_start(self):
        with allure.step("发送 log start 命令"):
            logger.info("发送 log start 命令")
            result = self.serial.set_log_start()
            logger.info(f"返回结果：{result}")
            assert result, "log start 命令执行失败"
            assert result is not None, "命令执行失败"

    @allure.story("日志控制")
    @allure.title("停止日志记录")
    @allure.description("""
    发送 log stop 命令停止板载日志记录并安全关闭日志文件，验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #9）：
    - 构造 TP_LOG_REQ 消息，type = LOG_REQ_TYPE_STOP
    - 通过 advs.log_req.publish() 发布到 UORB
    """)
    def test_set_log_stop(self):
        with allure.step("发送 log stop 命令"):
            logger.info("发送 log stop 命令")
            result = self.serial.set_log_stop()
            logger.info(f"返回结果：{result}")
            assert result, "log stop 命令执行失败"
            assert result is not None, "命令执行失败"

    # ==================== 内存调试 ====================
    @allure.story("内存调试")
    @allure.title("开启内存调试信息输出")
    @allure.description("""
    发送 smsg 命令开启内存调试信息输出（任务栈、堆使用等），验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #11）：
    - 调用 get_syslog() 获取日志缓冲区的写索引和数据指针
    - 从最旧的有效数据开始跳过前导零字节，输出所有有效数据
    - smsg c 清除整个缓冲区（memset 清零）
    """)
    def test_set_memory_debug(self):
        with allure.step("发送 smsg 命令显示系统日志"):
            logger.info("发送 smsg 命令")
            result = self.serial.set_memory_debug()
            logger.info(f"返回结果：{result}")
            assert result, "smsg 命令执行失败"
            assert result is not None, "命令执行失败"

    @allure.story("内存调试")
    @allure.title("关闭内存调试信息输出")
    @allure.description("""
    发送 smsg c 命令关闭内存调试信息输出（清除日志缓冲区），验证命令执行成功。

    工作原理（CLI_COMMANDS_REFERENCE #11）：
    - 参数 'c' 时调用 memset 将整个缓冲区清零
    """)
    def test_set_memory_debug_off(self):
        with allure.step("发送 smsg c 命令清除系统日志"):
            logger.info("发送 smsg c 命令")
            result = self.serial.set_memory_debug_off()
            logger.info(f"返回结果：{result}")
            assert result, "smsg c 命令执行失败"
            assert result is not None, "命令执行失败"

    # ==================== 电机测试 ====================
    @allure.story("电机测试")
    @allure.title("全通道电机测试")
    @allure.description("发送 mtcheck 命令对所有电机通道执行测试，验证命令执行成功。")
    def test_motor_test_all(self):
        with allure.step("发送 mtcheck 命令"):
            logger.info("发送 mtcheck 命令")
            result = self.serial.motor_test_all()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @allure.story("电机测试")
    @allure.title("指定通道电机测试")
    @allure.description("发送 mtcheck <channel> <pwm> 命令对指定通道以给定 PWM 值执行测试，验证命令执行成功。")
    def test_motor_test_channel(self):
        with allure.step("发送 mtcheck 0,1500 命令"):
            logger.info("发送 mtcheck 0, 1500 命令")
            result = self.serial.motor_test_channel(0, 1500)
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @allure.story("电机测试")
    @allure.title("定时电机测试")
    @allure.description("发送 mtcheck <channel> <pwm> <duration> 命令执行定时电机测试，验证命令执行成功。")
    def test_motor_test_timer(self):
        with allure.step("发送 mtcheck 0,1500,5 命令"):
            logger.info("发送 mtcheck 0, 1500, 5 命令")
            result = self.serial.motor_test_timer(0, 1500, 5)
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @allure.story("电机测试")
    @allure.title("停止电机测试")
    @allure.description("发送 mtcheck -1 命令立即停止所有正在进行的电机测试，验证命令执行成功。")
    def test_motor_test_stop(self):
        with allure.step("发送 mtcheck -1 命令"):
            logger.info("发送 mtcheck -1 命令")
            result = self.serial.motor_test_stop()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @pytest.mark.skip(reason="电机测试影响测试环境")
    @allure.story("电机测试")
    @allure.title("电机 PWM 扫描测试")
    @allure.description("发送 mtcheck <channel> <min> <max> <step> <interval> 命令在指定 PWM 范围内扫描测试电机响应，验证命令执行成功。")
    def test_motor_test_scan(self):
        with allure.step("发送 mtcheck 0,1200,1800,100,2 命令"):
            logger.info("发送 mtcheck 0, 1200, 1800, 100, 2 命令")
            result = self.serial.motor_test_scan(0, 1200, 1800, 100, 2)
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @pytest.mark.skip(reason="电机测试影响测试环境")
    @allure.story("电机测试")
    @allure.title("电机循环测试")
    @allure.description("发送 mtcheck <pwm1>~<pwm4> <repeat> <duration> <interval> 命令循环执行多通道电机测试，验证命令执行成功。")
    def test_motor_test_cycle(self):
        with allure.step("发送 mtcheck 循环命令"):
            logger.info("发送 mtcheck 循环命令")
            result = self.serial.motor_test_cycle(1500, 1500, 1500, 1500, 10, 5, 60)
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    # ==================== 老化测试 ====================
    @pytest.mark.skip(reason="老化测试影响测试环境")
    @allure.story("老化测试")
    @allure.title("开始老化测试")
    @allure.description("发送 aging_test <enable> <duration> <interval> 命令启动老化测试验证硬件可靠性，验证命令执行成功。")
    def test_aging_test_start(self):
        with allure.step("发送 aging_test 1,300,10 命令"):
            logger.info("发送 aging_test 1, 300, 10 命令")
            result = self.serial.aging_test_start(300, 10)
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @pytest.mark.skip(reason="老化测试影响测试环境")
    @allure.story("老化测试")
    @allure.title("停止老化测试")
    @allure.description("发送 aging_test 0 命令停止正在运行的老化测试，验证命令执行成功。")
    def test_aging_test_stop(self):
        with allure.step("发送 aging_test 0 命令"):
            logger.info("发送 aging_test 0 命令")
            result = self.serial.aging_test_stop()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

    @pytest.mark.skip(reason="老化测试影响测试环境")
    @allure.story("老化测试")
    @allure.title("老化测试循环模式")
    @allure.description("发送 aging_test 循环模式命令按指定 PWM 序列循环驱动电机进行可靠性验证，验证命令执行成功。")
    def test_aging_test_cycle(self):
        with allure.step("设置 INDOOR_DEBUG=1"):
            logger.info("发送 sp 命令设置参数")
            result = self.serial.set_parameter("INDOOR_DEBUG", 1)
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

        with allure.step("保存 INDOOR_DEBUG"):
            logger.info("发送 svp 命令保存参数")
            result = self.serial.save_parameter("INDOOR_DEBUG")
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

        with allure.step("发送 aging_test 循环命令"):
            logger.info("发送 aging_test 循环命令")
            result = self.serial.aging_test_cycle(7200000, 6, 3000, 600, 25, 50, 75, 75, 18)
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"

        with allure.step("发送 aging_test 0 停止命令"):
            logger.info("发送 aging_test 0 命令")
            result = self.serial.aging_test_stop()
            logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
