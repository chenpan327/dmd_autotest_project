# coding: utf-8

"""
X1 激光云台控制测试 — 云台模式（CLI）/ Lock 角度 / 通道匹配 / 激光限幅保护
（X1-REQ-GMBL-0001、0003~0006）

业务背景：
    X1 机型挂载激光云台负载。云台控制有三条通路：CLI `gimbal <mode>` 切
    工作模式（Init/Debug/LD Protection，Protobuf 下发云台子模块）；COMMAND_LONG
    183（MAV_CMD_DO_SET_SERVO）按 param7 子命令控云台 Lock 角度（=11 新版 /
    =5 旧版已废弃）与激光颜色（=4，param4 通道号，128 为广播）；解锁/上锁
    （command=400）联动激光功率限幅（上锁钳 ≤25≈10%）。本文件承载 GMBL 类
    需求用例（后续 GMBL 用例统一追加到本文件）。

    需求/用例库来源（l5_test 仓库，不入本仓库 git）：
        D:\\git\\l5_test\\无人机X1测试需求\\X1-REQ-GMBL-*.md
        D:\\git\\l5_test\\无人机X1测试用例库\\X1-TC-GMBL-*.md

用例对照（用例库编号 ↔ 本文件用例；2026-09-16 对齐现行用例库编号——
早期表格按旧草稿编号标注（旧 0002=gimbal 1 单项、旧 0003=LD Prot 单项、
旧 0005=循环一致性），现行库已重整：旧 0002 并入现 0001，旧 0003/0005
内容由 0001 综合流程覆盖，现 0002 起为 MAVLink 侧需求）：
    ┌────────────────────┬────┬──────────────────────────────────────┬────────┐
    │ 用例库编号          │优先│ 验证内容 ↔ 方法                       │ 状态   │
    ├────────────────────┼────┼──────────────────────────────────────┼────────┤
    │ X1-TC-GMBL-0001    │ P1 │ CLI 模式切换综合：三模式 + 无效参数    │ 已实现 │
    │                    │    │ test_gimbal_mode_control_flow        │        │
    │ X1-TC-GMBL-0002    │ P1 │ Follow 模式角向量控制及限位（单用例全  │ 已实现 │
    │                    │    │ AC：向量映射/arcsin 换算/50° 饱和）   │        │
    │ X1-TC-GMBL-0003    │ P1 │ Lock 角度锁定综合（单用例全 AC：基本/ │ 已实现 │
    │                    │    │ 边界/旧版指令/通道独立(间接)/机械限位）│        │
    │ X1-TC-GMBL-0004    │ P1 │ 通道匹配与上电识别综合（单用例全 AC：   │ 已实现 │
    │                    │    │ 匹配规则/广播激光/ADC 缺位说明）      │        │
    │ X1-TC-GMBL-0005    │ P0 │ 上锁激光限幅综合：DISARMED 限幅 + 解锁 │ 已实现 │
    │                    │    │ 无残留（危险·双层门控叠加）           │        │
    │ X1-TC-GMBL-0006    │ P0 │ 高度 <20m 激光关闭保护（skip 占位，   │ 占位   │
    │                    │    │ 待 HIL 假飞机/试飞环境）              │        │
    │ X1-TC-GMBL-0007    │ P0 │ failsafe/非 GUIDED 禁激光（真机=Debug │ 已实现 │
    │                    │    │ 豁免探针+主体缺位）                   │        │
    │ X1-TC-GMBL-0008    │ P1 │ 人工急停激光锁存（skip 占位，急停命令  │ 占位   │
    │                    │    │ 口径待确认）                          │        │
    │ X1-TC-GMBL-0009    │ P1 │ 安装方向一致性检查（skip 占位）        │ 占位   │
    │ X1-TC-GMBL-0010    │ P1 │ 心跳掉线分级断电（skip 占位）          │ 占位   │
    │ X1-TC-GMBL-0011    │ P1 │ 云台热插拔重连（拔出→重插→恢复受控，   │ 已实现 │
    │                    │    │ 人工拔插+行为探针）                   │        │
    │ X1-TC-GMBL-0012    │ P1 │ RGB 接收/G/B 输出/R 抑制（相机判读，   │ 已实现 │
    │                    │    │ ≤25 档；重复帧统计缺位）              │        │
    │ X1-TC-GMBL-0016    │ P1 │ 五态激光权限矩阵（真机=INIT/LD_PROT    │ 已实现 │
    │                    │    │ 禁+DEBUG 允；READY 缺位，CALIB 见     │        │
    │                    │    │ 0029/38）                             │        │
    │ X1-TC-GMBL-0024    │ P1 │ 舵机 Pitch/Roll 轴映射（单轴指令+      │ 已实现 │
    │                    │    │ 人工判读；UART 走向缺位）             │        │
    │ X1-TC-GMBL-0026    │ P0 │ 降落保护收纳/卸力（真机=上置双轴卸力，  │ 已实现 │
    │                    │    │ 手动验证；下置/通道无效缺位）         │        │
    │ X1-TC-GMBL-0029/38 │ P1 │ 校准族：零点校准触发链路+校准中激光抑制 │ 已实现 │
    │                    │    │ test_gimbal_calibration_flow（探测口径 │（探测）│
    │                    │    │ p1=8 猜值+危险门控；0016 CALIB 落地）  │        │
    │ X1-TC-GMBL-0037    │ P0 │ 激光通道控制——已被 0004（广播）/0005    │ 已覆盖 │
    │                    │    │ （钳制实锤）/0007（failsafe）覆盖     │        │
    └────────────────────┴────┴──────────────────────────────────────┴────────┘

    优先级区分（2026-09-17 起）：@pytest.mark.p0/p1（pytest.ini 已注册，
    `-m p0` / `-m p1` 可单独执行）+ @allure.severity（P0=BLOCKER、
    P1=NORMAL）+ 标题 P0/P1 前缀，三处口径一致。

真机判据口径（用例库按 HIL 台架编写 → 真机环境的判据换算，重要）：
    用例库的验收动作为 protobuf 总线抓包、GLB_VAR 调试器读取、UORB 主题
    监听与假飞机注入；真机 MAVLink 环境均无观测手段，判据换算与缺口如下：
    - 通用（0001/0003/0004）：CLI/COMMAND 正向回显或 ACK result=0 + 反向
      无 NAK/unknow（固件对未知子命令也回 ACK，仅看 ACK 会漏判——协议
      口径铁律）；protobuf / GLB_VAR / UORB 无观测手段，如实以回显为
      最高可达判据，不装能验；云台物理动作无遥测报文，需人工观察
    - ★ X1-TC-GMBL-0001 无效参数分支的两条 HIL 验收动作真机无法执行：
      「协议分析工具抓包确认无 protobuf 消息发出」——整机内部总线无抓包
      接入点，MAVLink 遥测亦无 mode 字段（msg 8 仅版本号、msg 204 仅
      温度告警）；「GLB_VAR::gimbal_mode 保持不变」——无调试器亦无查询
      命令（前辈口径是借查询命令把变量打进回显，如 cur_mode→`mode`，
      gimbal_mode 无配套命令）。两点均为验证缺口，改用"unknow 回显 +
      set gimbal to 缺席"判无效参数被拒，行为探针（合法切换仍按已知
      状态正常工作）旁证状态未被破坏；缺口待 HIL 台架建成或固件增加
      gimbal 查询命令后补全
    - 0002 Follow 向量：UORB type/x/y/z/channel 字段赋值（AC-002/003）
      无监听手段；[-1,1] 线性映射与正负方向（AC-005）、arcsin 换算到位/
      50° 饱和/0.766 临界值（AC-006）均无遥测——ACK + 整定 + 人工观察
    - 0003 Lock 角度：UORB TP_SET_GIMBAL 字段赋值（AC-002/003）无监听
      手段；云台到位锁定（AC-004）与 ±50° 饱和位置（AC-008）无遥测
      （msg 8 仅 gimbal_version 版本号）——ACK + 整定 + 人工观察；
      AC-006 旧版指令"不能到达云台"仅能人工观察无动作（ACK result 不
      区分下游通道路由）；AC-007 多通道独立采用单云台间接口径——向他
      通道发锁定指令本通道无响应 + 本通道指令正常生效（隔离即独立的
      单机可达判据），两在线云台互不干扰的直接验证仍需多云台环境
    - 0004 通道匹配：指令被云台丢弃与否无回执差异（AC-001），判据 =
      ACK 仅记录 + 云台无动作人工观察 + 本机通道行为探针旁证；ADC 上电
      识别/初始化时序/拔出清理（AC-002~004/006）需 HIL 台架，步骤内
      缺位说明（不 skip 整条用例）；AC-005 广播"全部云台同时受控"
      真机单云台只能验证在线云台生效（多云台缺口如实标注）
    - 0005 限幅：云台接收值（线上值）无遥测 → 判据以相机量化亮度为
      代理（固定手动曝光 -9 下绿色光斑掩码命中像素数随功率单调增，
      blink 实测口径）：上锁态 g=64 与 g=25 同档=限幅生效、g=13 更暗=
      不误限幅、解锁态 g=64 明显亮于上锁态同值=无残留；★比值阈值初值
      待真机首跑校准；数值保守（最大请求 25%=64，限幅失效时最大 25%
      输出；满功率 255 验证留待 CAN 抓包/遥测手段后补）；armed 前置/
      翻转以 packed_state 回读实锤；相机不可用时降级 ACK+人工观察
    - 0006 高度保护：触发需 HIL 假飞机注入 pos_z 或真机飞行穿越 20m
      门限；台架 Debug 通路激光可正常点亮（2026-09-14 标定/blink 真机
      实测先例）说明保护链路在该通路不可达或未启用，台架无法区分判定
      → skip 占位
    - 0007 异常禁激光：主体（非 DEBUG 态 failsafe/非 GUIDED 关激光）
      需 READY 态（解锁且 >20m）真机不可达；可跑部分为 **Debug 豁免
      探针**（注入 ffs / 切 LOITER 下激光保持，★推定待真机——若被关
      = 豁免不成立记问题单；判据=相机光斑存在性，相机不可用降级
      人工）；ffs 档位覆盖 battery/wp/fence/ekf/crash 五类（GCS-04
      实测），radio/gcs/igniter 无注入命令；AC-003/004 缺位
    - 0008 急停锁存：前置需剧本+READY；急停关闭/锁存解除命令号未
      确认（40003 为飞行急停，激光联动待查）→ skip 占位
    - 0009 安装方向：剧本方向配置/上报消息/上电监测均 HIL 手段 →
      skip 占位（真机旁证=通道 3 上视一致，见 0004）
    - 0010 心跳掉线：停心跳/供电与命令下发监测/时序测量均 HIL 手段
      → skip 占位（gimbal_scaled 遥测若可读可升级真机观测，见
      GMBL-0041）
    - 0011 热插拔：真机单云台主场景（拔出→重插→恢复受控），判据间接
      =重插后通道 3 指令生效（行为探针）；供电/DAV 寻址/对象清理与
      另两插拔场景（整机断电重启）缺位；拔插为人工操作（固定时间窗
      +附件提示，运行时需操作者在场）
    - 0012 RGB 接收：相机光斑（绿/蓝分检，_verify_spot）；>25 值被
      DISARMED 钳制（0005 实锤 Debug 不豁免）→ 取 ≤25 档；R 抑制 =
      仅 R 指令验无任何光斑（负向）；AC-003 重复帧统计缺位
    - 0016 权限矩阵：真机 3/5 态——INIT/LD_PROT 禁（相机验不亮）、
      DEBUG 允（验亮，正向对照）；禁态 ACK 仅记录（拒绝在下游权限层）；
      READY（飞行）缺位；CALIB 分支由 0029/38 校准族用例承载（校准中
      验不亮，探测口径·危险门控）
    - 0024 轴映射：判据=人工观察指令轴↔运动轴一致（无遥测，两舵机
      体积可辨）；UART 报文走向/舵机规格对应缺位（真机验行为层映射）
    - 0026 降落策略：真机上置挂载（通道 3）→ AC-002 双轴卸力（人工
      观察+手动转动验证）；下置（AC-001）需换装、通道无效（AC-003）
      需 HIL——缺位；★实测"切 LD_PROT 走收纳位"与需求"上置双轴卸力
      不移动"的矛盾由手动验证环节裁决（主动走位 vs 卸力自然下垂）

测试流程（终端开关由 fixture 前置/后置管理，不占步骤；各用例独立成块，
均可单独执行）：

X1-TC-GMBL-0001（CLI 模式切换综合 [正常流程 + 异常场景]）：
    [前置] 打开终端 — 初始化 GroundControlStation，等一跳心跳确认链路，
           SR0_CONSOLE 复位后置 20 打开 CLI→CONSOLE 路由（回显
           Save/Set OK）；固件版本/SN 写入 allure 环境信息
     1. gimbal 1 切至 Debug（已知模式，无效参数"状态不变"的判定基准）
     2. 发送 gimbal 5（超范围数字）→ 回显命中 "unknow gimbal cmd"，
        且不得含 "set gimbal to"（判据方向与正常切换相反）
     3. 发送 gimbal a（非数字）→ 同上
     4. gimbal 2 切至 LD Protection — gimbal 0 的合法前驱；兼作行为
        探针：无效命令后合法切换仍正常，状态未被破坏（旁证，直接
        证据缺口见"真机判据口径"★条目）
     5. 发送被测命令 gimbal 0
     6. 验证回显命中 "set gimbal to init mode" 且无 NAK/unknow 失败标记
    [后置] 清理 — 恢复 Init 模式（已在 Init 则跳过）、关激光、归零、
           SR0_CONSOLE=0 关路由、关闭地面站 UDP 套接字

X1-TC-GMBL-0002（Follow 模式角向量控制及限位 [边界条件]，单用例全 AC）：
  test_gimbal_vector_follow_control（AC-001~006；每步步前向量归零回
  默认位置，动作从同一起始基准出发便于观察归因）：
    [前置] 打开终端；gimbal 1 切 Debug（Follow 向量在 Debug 模式使用，
           X1-REQ-GMBL-0002 §4）；向量 (0,0,0) 归零起始基准
     1. 归零 → 基本向量 (0.5, -0.3, 0.2, 通道3) → ACK result=0（AC-001
        指令接受；AC-002/003 UORB 字段无观测手段、AC-004 三轴运动
        人工观察）
     2. 三轴遍历（各轴步前归零、取值彼此错开便于归因）：x 轴
        -1/-0.5/0/0.5/1、y 轴 0.8/0.3/-0.6、z 轴 -0.9/0.4 → 各 ACK=0
        （AC-005 线性映射与正负方向人工观察；z/Yaw 无执行机构时无
        动作属预期，如实记录不判失败）
     3. 归零 → x 轴 |v|=0.5（< 0.766）→ 换算 arcsin(0.5)=30° < 50°，
        到位人工判读（AC-006）
     4. 归零 → x 轴 |v|=0.9（> sin50°≈0.766）→ 饱和于 +50° 机械限位
        人工判读（AC-006）
     5. 归零 → x 轴 |v|=0.766（sin50° 临界值）→ 恰 50° 边界不越界
        人工判读（AC-006）
     6. 模式门控（超出库 AC 的补充检查，★待真机验证）：归零后切至
        LD Protection / Init 各发向量 (0.5,0,0) → ACK 仅记录、待切换
        自身动作（LD_PROT 收纳）静止后判"无进一步动作"；行为探针切回
        Debug 向量恢复生效（区分门控与链路失效）
    [后置] 清理 — 探针后向量 (0,0,0) 归零（用例止于 Debug）+
           fixture 兜底恢复 Init

X1-TC-GMBL-0003（Lock 模式角度锁定及限位 [边界条件]，单用例全 AC；
每步步前 Lock(0°,0°) 归零）：
  test_gimbal_lock_angle_control_flow（AC-001~008）：
    [前置] 打开终端；gimbal 1 切 Debug（Lock 模式在 Debug 模式使用，
           X1-REQ-GMBL-0003 §4）
     1. 归零 → Lock(30°, -20°, 通道3) → ACK result=0（AC-001 指令
        接受；AC-002/003 UORB 字段无观测手段、AC-004 到位锁定人工
        观察）
     2. 归零 → 边界四发 (±180°,0)/(0,±180°) → 各 ACK=0（AC-005；
        >±50° 实际饱和于机械限位，见步骤 7/8）
     3. 归零 → 旧版指令 param7=5（旧轴序，无 channel 字段）→ ACK 仅
        记录、云台无动作人工判读（AC-006）
     4. 归零 → 他通道（1=10°/2=40°，库用例原值）各发锁定指令 → 本
        通道（3）无响应人工判读（AC-007 单云台间接口径）
     5. 本通道 Lock(40°,0°) → ACK=0 正常锁定（AC-007 正向半边，兼前
        两条负向步骤后的链路完好证据；两在线云台互不干扰的直接验证
        仍需多云台）
     6. 归零 → Lock(120°,0°)（超 +50°）→ ACK=0，饱和位人工判读（AC-008）
     7. 归零 → Lock(0°,-90°)（超 -50°）→ ACK=0，饱和位人工判读（AC-008）
    [后置] 清理 — Lock(0°,0°) 归零 + fixture 兜底

X1-TC-GMBL-0004（通道匹配规则与上电识别，单用例全 AC；弱化判据在
方法 docstring 首部声明）：
  test_gimbal_channel_match_flow（AC-001~006）：
    [前置] 打开终端 + gimbal 1 切 Debug + Lock(0°,0°)
     1. 向非本机通道 1 发 Lock(30°,-20°) → ACK 仅记录（通道路由丢弃
        发生在下游，无回执差异）；云台无动作人工观察
     2. 行为探针：向本机通道 3 发 Lock(30°,-20°) → ACK=0；云台运动
        人工观察（旁证在线通道=3，与上视挂载组 1/3 一致 → AC-002 弱
        旁证）
     3. 广播 128 绿色 g=3 → ACK=0；人工判读激光点亮（AC-005）
     4. 广播 128 关闭 (0,0) → ACK=0；人工判读激光熄灭（单云台只能证
        广播对在线云台生效，"全员同时受控"为多云台缺口）
     5. 上电 ADC 识别与初始化/卸载时序（AC-002~004/006）— HIL 台架
        项，步骤内缺位说明（真机旁证=通道 3 指令有效），不 skip
    [后置] 清理 — 归零 + fixture 兜底关激光

X1-TC-GMBL-0005（上锁激光功率限幅 10% [异常场景] P0，单用例全 AC，
危险·双层门控叠加——两环境变量须同设；弱化判据在方法 docstring 首部
声明；相机判亮度 + 数值保守——最大请求 25%（g=64））：
  test_laser_power_clamp_flow（AC-001~004）：
    [前置] 拆桨+限流台架；packed_state 确认上锁（armed=1 则先归位
           上锁）、记初始模式；gimbal 1 切 Debug（激光输出权限，
           GMBL-0016）；开相机（可选，失败降级人工判读）
     1. 上锁态 g=64（25%，超门限）→ ACK=0；相机测亮度（预期被钳 ≈25）
     2. 上锁态 g=25（恰 10%，原值）→ ACK=0；相机测亮度（基准档）
     3. 上锁态 g=13（5%，低于门限）→ ACK=0；相机测亮度（应更暗）
     4. 限幅判读断言：g=64 与 g=25 亮度同档（限幅生效）、g=13 严格
        更暗（不误限幅）——掩码命中像素比值，★阈值待首跑校准
     5. 上锁态扫描 g=0/13/25/64 → 各 ACK=0（AC-003 范围保持不可验，
        判据仅 ACK）
     6. 关激光（解锁段前安全位）→ 相机验证熄灭
     7. SET_MODE 切 mode=4（play，解锁前置——GCS-03 口径）并回读确认
     8. 指令解锁 cmd400 p1=1 → packed_state.armed 翻 1（ACK result=0
        存在假成功，以 armed 回读为执行实锤；失败附 dmsg 拒绝原因）
     9. 解锁态 g=64 → ACK=0；亮度应明显高于上锁态同值（限幅解除无
        残留，比值断言★待校准）；armed 保持复查（台架限流 ~5s 自动
        落锁鉴别）
    10. 解锁态 g=13 → ACK=0；低值原值下发（次序记录）
    [后置] 恢复（finally，覆盖步骤 1 起——相机在前置打开，任何步骤
           失败都须关激光/关相机，防进程带相机退出卡死 DShow，09-17
           实锤）— 广播关激光 → 关相机 → cmd400 p1=0 上锁（armed 回
           0；重复上锁可能幂等拒绝，清理段不判 ACK）→ SET_MODE 恢复
           初始模式

X1-TC-GMBL-0006（高度 <20m 激光关闭保护 [异常场景] P0，skip 占位）：
  test_laser_low_altitude_protection — 高度触发需 HIL 假飞机注入 pos_z
  或真机飞行 >20m 往返；台架 Debug 通路激光可点亮（保护不可达），
  响应时序 ≤1s 需示波器/时标——待 HIL/试飞环境补全

X1-TC-GMBL-0007（飞机异常禁止激光 [异常场景] P0，单用例全 AC；弱化
判据在方法 docstring 首部声明；真机可跑部分 = Debug 豁免探针）：
  test_laser_failsafe_guard（AC-001~004）：
    [前置] 打开终端；相机（按名 FF-Camera，可选）；gimbal 1 切
           Debug；点亮绿激光 g=13（g=3 实锤漏检：核心过曝掉出掩码）
     1. 基线：相机确认光斑存在
     2. 逐档注入 ffs（1 低电/2 航点/3 围栏/4,1,0,1 EKF/5 坠机）→
        Fake 回显确认 + 相机验光斑保持（Debug 豁免★推定）→ ffs 0
        清除（每档验毕即清）
     3. SET_MODE 切 LOITER(5)（非 GUIDED）→ 相机验光斑保持（豁免★）
        → 切回 mode 4（play 表演常态）
     4. 主体缺位说明：非 DEBUG（READY）态 failsafe/非 GUIDED 关激光、
        AC-003 云台不推断状态、AC-004 清零帧补发——待试飞/HIL 补全
        （radio/gcs/igniter 三类 failsafe 无 CLI 注入命令）
    [后置] 恢复（finally）— 关激光 → ffs 0 清残留注入 → 关相机

X1-TC-GMBL-0008（人工急停激光锁存 [异常场景] P1，skip 占位）：
  test_laser_estop_latch — 前置需剧本运行+READY 输出态（解锁且
  >20m）；急停关闭/锁存解除命令号未确认（40003 为飞行急停，激光
  联动待查）——待试飞/HIL 与命令口径确认后补全
X1-TC-GMBL-0009（安装方向一致性 [正常流程] P1，skip 占位）：
  test_gimbal_mount_direction_check — 剧本方向配置/上报消息/上电
  监测均 HIL 手段；真机旁证=通道 3 上视一致（见 0004）
X1-TC-GMBL-0010（心跳掉线分级断电 [异常场景] P1，skip 占位）：
  test_gimbal_heartbeat_timeout — 停心跳/内部信号监测/时序测量均
  HIL 手段（gimbal_scaled 遥测可读时可升级真机观测，见 GMBL-0041）

X1-TC-GMBL-0011（热插拔重连 [异常场景] P1，人工拔插交互用例）：
  test_gimbal_hot_plug（AC-001~003 主场景）：
    [前置] gimbal 1 Debug + Lock(30°,0°) 受控基线
     1. 人工拔出云台 CAN/负载线（10s 窗口，附件提示）
     2. 拔出态 Lock(40°,0°) → ACK 仅记录（离线回执行为）
     3. 人工重插（15s 窗口+重连初始化）
     4. Lock(40°,0°) → ACK=0 + 云台运动 = 恢复受控（重连间接判据）
     5. 缺位说明（另两场景/内部监测/双云台互不影响）
X1-TC-GMBL-0012（RGB 接收与 G/B 输出 [正常流程] P1，相机判读）：
  test_laser_rgb_receive（AC-001~003）：绿 g=20 亮/关灭 → 蓝 b=20
  亮/关灭 → 双路 (g=20,b=13) 双色 → 仅 R (255,0,0) 验无任何光斑
  （R 抑制，负向）→ AC-003 重复帧统计缺位
X1-TC-GMBL-0016（五态激光权限矩阵 [正常流程] P1）：
  test_laser_state_permission_matrix：INIT 态发 g=13 验不亮 → Debug
  验亮（正向对照）→ LD_PROT（等收纳静止 3s）验不亮 → 缺位说明
  （READY 待试飞；CALIB 分支由 0029/38 校准族承载）
X1-TC-GMBL-0024（舵机 Pitch/Roll 轴映射 [正常流程] P1）：
  test_gimbal_servo_axis_mapping：步前归零节奏——Roll+30 单轴 /
  Pitch+30 单轴 / 反向 -30 复核 / 混合 (20,-20) 两轴同动；人工判读
  指令轴↔运动轴一致；UART 走向/规格对应缺位
X1-TC-GMBL-0026（降落保护收纳/卸力策略 [正常流程] P0）：
  test_gimbal_landing_stow：Lock(30°,-20°) 离开收纳位 → gimbal 2
  触发 → 人工判读是否自主走收纳位（上置预期不移动）→ 手动转动两轴
  验卸力（上置=双轴卸力）→ 第二轮重复触发验稳定 → 下置/通道无效缺位
X1-TC-GMBL-0029/0038（校准族 [正常流程] P1，探测口径·危险门控）：
  test_gimbal_calibration_flow（0038 AC-001~003 + 0029 AC-001/004，
  0016 CALIB 分支在此落地）：
    [前置] 相机 + gimbal 1 Debug + g=13 验亮（激光链路正向基线）
     1. Debug 态（非 INIT）触发 40040(p1=8,p2=1) → 激光仍可控
        （云台未被校准抢占 = 不触发旁证；0038 AC-002）
     2. 回 Init（Debug→LD_PROT→Init 单向链，满足校准前置）
     3. Init 触发校准 → 人工判读窗（黄灯闪/手试两轴卸力，0029
        AC-004）+ TP_SENSOR_CALI 发布率采样（启动证据，GCS-15 通道）
     4. 校准中发 g=13 → 相机验不亮（0016 CALIB 分支 + 0029
        AC-001 后半；校准期出光即违例，强断言）
     5. 35s 超时窗（30s 上限+余量）→ 率回落 + 黄灯停（0029 AC-002
        上限 + 0038 AC-003 回落）
     6. 切 Debug → g=13 验亮（权限恢复=校准退出未卡死）→ 停止
        兜底 (p1=0,p2=2) + 发布率趋势汇总
     7. 缺位说明（AC-003 逐轴内部流程/卡住注入 HIL/READY 分支）
X1-TC-GMBL-0037（激光通道控制 P0）：不新写——广播=0004✓、未解锁
  钳制=0005 相机实锤✓、failsafe 关闭=0007 主体同源缺位；644 报文
  补强待 CAN 抓包能力

危险门控（GMBL-0005 单用例默认 skip；两个环境变量须**同时设置**——
整条用例按最高危险级门控。定义见文件常量区，模式同 fc_basic_base）：
    GMBL_ENABLE_LASER_OVERDRIVE=1 — 允许发送超限激光值（绕过
        _laser_color 护眼限幅守卫 25）。保守口径：最大只发 64（25%）
        ——限幅失效时最大 25% 输出（远低于满功率），验证">10% 被钳"
        即足以证明限幅存在；满功率（255）验证留待 CAN 抓包/遥测观测
        手段后补。确认光路无人后再开
    GMBL_ENABLE_ARMED_FULL_POWER=1 — 解锁段（步骤 8~10）真解锁：
        拆桨 + 限流电源台架（GCS-03 危险组同款前提），解锁后电机可能
        转动；台架限流电源若 ~5s 自动落锁，跑前需 CLI
        `sp FS_BATT_ACT: 0` 并在试飞前恢复 1（GCS-03 口径）
    GMBL_ENABLE_CALIB_PROBE=1 — 云台校准族（GMBL-0029/0038）：零点
        校准写原点落盘（跑后建议人工重校）+ 校准中舵机卸力（轴可能
        自然下垂，注意接挡）；param1=8 为推定猜值。需操作者在场
    Git Bash 示例：
        GMBL_ENABLE_LASER_OVERDRIVE=1 GMBL_ENABLE_ARMED_FULL_POWER=1 python main.py --device_type X1 --test_suites Release_Testing
    PowerShell 示例：
        $env:GMBL_ENABLE_LASER_OVERDRIVE = "1"; $env:GMBL_ENABLE_ARMED_FULL_POWER = "1"

协议整理（依据 l5_test 需求文档 + 真机实测 172.19.210.29）：
    ┌──────────────────┬──────────────────────────────────────────────┐
    │ 动作              │ 指令格式                                     │
    ├──────────────────┼──────────────────────────────────────────────┤
    │ 终端路由开关 ★    │ PARAM_SET (msg_id=23): SR0_CONSOLE=20 开/0 关│
    │ (2026-09-04 抓包  │ 置 20 后 CLI 才桥接到 CONSOLE(48)，回        │
    │  逆向确认)        │ "Save/Set 'SR0_CONSOLE' OK"。缺这步无回显！  │
    ├──────────────────┼──────────────────────────────────────────────┤
    │ 云台模式 (CLI)    │ CONSOLE (msg_id=48): `gimbal <mode>`         │
    │ (X1-REQ-GMBL-0001)│ 0=Init 1=Debug 2=LD Protection               │
    │   实测: gimbal 1 ✓│ 无效参数回 "unknow gimbal cmd"               │
    ├──────────────────┼──────────────────────────────────────────────┤
    │ 云台角度 Lock 新版 │ COMMAND_LONG 183: param1=roll param2=pitch   │
    │ (X1-REQ-GMBL-0003)│ param4=通道(1~4) param7=11；[-180,180]       │
    │   实测: ACK=0 ✓   │ 机械限位 ±50° 超出饱和；Debug 模式使用       │
    ├──────────────────┼──────────────────────────────────────────────┤
    │ 云台角度-向量形式  │ COMMAND_LONG 183: param1/2/3 = x/y/z 向量   │
    │ (X1-REQ-GMBL-0002)│ 分量（Roll/Pitch/Yaw，[-1,1]）param7=10；   │
    │ (command_183 json)│ 舵机角=arcsin(分量)，|v|>sin50°≈0.766 饱和  │
    ├──────────────────┼──────────────────────────────────────────────┤
    │ 云台角度 旧版 ★   │ COMMAND_LONG 183: param7=5, param1=yaw       │
    │ (command_183 json │ param2=roll param3=pitch——缺 channel 字段，  │
    │  标注"不再使用")  │ 不能到达云台（GMBL-0003 AC-006 验其不可用）  │
    ├──────────────────┼──────────────────────────────────────────────┤
    │ 激光颜色          │ COMMAND_LONG 183: param7=4, param2=g         │
    │ (X1-REQ-GMBL-0004 │ param3=b（param1=r 恒 0，无红光）；rgb 全 0  │
    │  §2 / LASER-0006) │ 关激光；param4=通道，128=广播全员生效        │
    ├──────────────────┼──────────────────────────────────────────────┤
    │ 解锁/上锁         │ COMMAND_LONG 400: param1=1 解锁 / 0 上锁；   │
    │ (fc_basic 真机实锤│ ⚠ ACK result=0 仅代表转发成功，拒绝时照样回  │
    │  GMBL-0005 AC-004)│ 0——armed 以 packed_state(msg 5) 回读为准    │
    ├──────────────────┼──────────────────────────────────────────────┤
    │ 模式切换          │ SET_MODE (msg_id=11): custom_mode=4(play)    │
    │ (GCS-05 枚举实锤) │ base_mode=0, target_system=1；mode=4 为解锁 │
    │                   │ 前置（GCS-03 口径，stab/rtl 下解锁被拒）    │
    ├──────────────────┼──────────────────────────────────────────────┤
    │ 云台校准触发 ★猜  │ COMMAND_LONG 40040: param1=类型（8=云台，    │
    │ (X1-REQ-GMBL-    │ 推定值待真机验证）param2=1 启动/2 停止；飞控 │
    │  0029/0038)      │ 仅在云台 Init 态转发 CALIBRATE_GIMBAL(34)   │
    │                   │ 至云台（FC 内部，GCS 不可直达）；校准中云台 │
    │                   │ 心跳报 calibrating → FC 进 CALIB 态         │
    └──────────────────┴──────────────────────────────────────────────┘

    注意事项：
    - ★ 终端握手是前置条件：固件默认不桥接 CLI 到 CONSOLE(48)，必须先
      PARAM_SET(23) SR0_CONSOLE=20（恒定先复位再置 20，值未变时固件
      不回显）。缺这步 CLI 无回显，曾被误判为"CLI 挂死"
    - 云台模式单向切换：Init → Debug → LD Protection → Init，Debug 不能
      直接切回 Init——gimbal 0（切 Init）只接受 LD Protection 前驱
    - Lock 模式在 Debug（CLI 手动）模式使用（GMBL-0003 §4）
    - 模式切换的物理动作（2026-09-17 真机实测钉口径）：切 LD Protection
      （gimbal 2，落地保护）触发收纳，云台走到收纳位（≠机械中位
      0°/0°；GMBL-0026 降落收纳策略同源）；切 Init（gimbal 0）不触发
      运动（09-14「Init 不自动回中」依然成立——当时收纳发生在途经的
      LD_PROT 一步，未归因）。故 teardown 兜底（归零→LD Prot→Init）
      终态=收纳位；Lock/向量归零兜底仍保留（restore 被跳过的路径下
      保证确定性，未进 Debug 时为无害 no-op）
    - 向量/角度控制仅在 Debug 模式生效——切至 LD Protection/Init 后
      发指令应无动作（模式门控）。舵机指令权限无明文（★待真机验证），
      推定依据：GMBL-0002/0003 §4"在 Debug 模式使用" + GMBL-0016 状态
      权限矩阵同构（激光在 INIT/LD_PROT/CALIB 明文禁止、DEBUG 允许，
      舵机按同一状态机推定同构）；门控判据 = ACK 仅记录 + 无进一步
      动作人工观察（切换自身的收纳动作不计，待静止后再发）+ 切回
      Debug 行为探针
    - 旧版 param7=5 与新版 param7=11 轴序不同（旧 yaw/roll/pitch、新
      roll/pitch + channel）——旧版缺 channel 字段是"不能到达云台"的
      根因（GMBL-0003 AC-006）
    - 固件对未知子命令仍回 ACK（如 "unknow gimbal cmd"），断言须同时检查
      NAK / unknow 失败标记，不能只看 ACK；负向用例（旧版指令/错通道）
      ACK result 仅记录不判据（expect_result=None）
    - 无效参数步骤（X1-TC-GMBL-0001）判据方向相反：回显命中
      "unknow gimbal cmd" 是预期，出现 "set gimbal to" 反而是失败
    - 上锁限幅 10%（≈25）是飞控侧行为（GMBL-0005），云台接收值无遥测；
      _laser_color 的 LASER_POWER_LIMIT=25 护眼守卫在 0005 两条门控
      用例中被有意绕过（直接 _send_command_long 发 param7=4）

分层：
    收发与云台/激光业务方法（_gimbal_mode / _gimbal_restore_init /
    _gimbal_lock_angle / _laser_color）及协议常量见 X1/conftest.py 的
    _GimbalLaserBase；前置/后置 fixture 留在本文件（后置兜底顺序按
    物理依赖：关激光 → 归零 → 恢复 Init → 关路由 → 关地面站）。
    0005 解锁段的状态读取（heartbeat_dmd→packed_state）与 armed 轮询以
    用例内嵌套函数实现（仅单用例消费，sweep_path 先例，不上类层/共享层）
    ——复用 fc_basic_base 已实锤的帧常量与命令号（HEARTBEAT_DMD_HEX /
    CMD_ARM_DISARM / SET_MODE），不继承 FCBasicBase 整套传输层。
"""

import os
import re
import time

import pytest
import allure

from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation
from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    ARM_P1, CMD_ARM_DISARM, DISARM_P1, HEARTBEAT_DMD_HEX,
    MSG_ID_PACKED_STATE, MSG_ID_SET_MODE, CMD_CALIB_SENSOR)
from src.Script.Drone_Show.X1.conftest import (
    CMD_DO_SET_SERVO, GIMBAL_CHANNEL, GIMBAL_MODE_DEBUG, GIMBAL_MODE_INIT,
    GIMBAL_MODE_LD_PROT, LASER_BROADCAST_CHANNEL, _GimbalLaserBase)
from utils.laser_camera import LaserSpotCamera, encode_jpg
from utils.logger import log_manager


# ============================================================================
# 安全门控（GMBL-0005 危险用例，模式同 fc_basic_base 的环境变量门控）
# ============================================================================

# 第一层：超限激光发送开关——DISARMED 限幅验证（AC-001~003）需发送超过
# 护眼限幅 25 的激光值。保守口径：最大只发 64（25%）——限幅失效时最大
# 25% 输出（远低于满功率），验证">10% 被钳"即足以证明限幅存在；满功率
# （255）验证留待 CAN 抓包/遥测观测手段后补。默认 skip，运行前确认
# 光路无人
ENABLE_LASER_OVERDRIVE = os.environ.get("GMBL_ENABLE_LASER_OVERDRIVE", "0") == "1"

laser_overdrive_gate = pytest.mark.skipif(
    not ENABLE_LASER_OVERDRIVE,
    reason="危险用例：发送超限激光值（最大 64=25%，若固件 DISARMED 限幅"
           "失效会短时 25% 输出），需设置环境变量 GMBL_ENABLE_LASER_OVERDRIVE=1"
           "并确认光路安全后执行")

# 第二层：真解锁 + 解锁态激光开关（GMBL-0005 AC-004）——需拆桨+限流电源
# 台架（GCS-03 危险组同款前提），解锁后电机可能转动；台架限流电源若
# ~5s 自动落锁，跑前需 CLI sp FS_BATT_ACT: 0（试飞前恢复 1）
ENABLE_ARMED_FULL_POWER = os.environ.get("GMBL_ENABLE_ARMED_FULL_POWER", "0") == "1"

armed_full_power_gate = pytest.mark.skipif(
    not ENABLE_ARMED_FULL_POWER,
    reason="高危用例：真解锁（电机可能转动）+ 解锁态激光请求，需拆桨+"
           "限流台架并设置环境变量 GMBL_ENABLE_ARMED_FULL_POWER=1"
           "（须叠加 GMBL_ENABLE_LASER_OVERDRIVE=1）后执行")

# 第三层：云台校准族（GMBL-0029/0038）——零点校准**写原点落盘**（测试后
# 建议人工重校，GCS-15 危险组同款理由）+ 校准中舵机卸力（轴可能自然下垂，
# 注意接挡）；且 param1=8 为推定猜值，若固件将其解析为其他校准类型会真跑
# 该校准。默认 skip，运行需操作者在场（黄灯/卸力人工判读）
ENABLE_CALIB_PROBE = os.environ.get("GMBL_ENABLE_CALIB_PROBE", "0") == "1"

calib_probe_gate = pytest.mark.skipif(
    not ENABLE_CALIB_PROBE,
    reason="危险用例：零点校准写原点落盘（测试后建议人工重校）且校准中"
           "舵机卸力（轴可能自然下垂，注意接挡），需设置环境变量 "
           "GMBL_ENABLE_CALIB_PROBE=1、确认云台周围无障碍且操作者在场"
           "后执行")


# ============================================================================
# 相机光斑判据辅助（模块级，0007/0012/0016 共用；blink 文件同款模式）
# ============================================================================

def _verify_spot(camera, color, expect_on, tag, fail_hint=""):
    """光斑存在性双向判据（camera 为 None 时降级人工提示，不 fail）

    expect_on=True：断言检出指定颜色（"green"/"blue"）光斑，画面+检测值
    进报告；expect_on=False：断言绿/蓝均无光斑（任一检出即失败，防余辉/
    残留/误检——blink _verify_spot_off 同口径）。点亮值须 ≥g13（检测
    下限实锤，见 0007 注释）。fail_hint 追加到失败消息（调用点带语境）。
    """
    if camera is None:
        log_manager.log_and_attach(
            f"{tag}：相机不可用，人工判读（预期"
            f"{'点亮' if expect_on else '熄灭'}）", f"光斑判读 {tag}")
        return
    time.sleep(0.3)   # 光斑稳定/余辉消散
    frame = camera.capture()
    if expect_on:
        result = camera.detect_spot(frame, color)
        allure.attach(encode_jpg(camera.annotate(frame, result)),
                      name=f"光斑判读 {tag}",
                      attachment_type=allure.attachment_type.JPG)
        assert result.found, (
            f"{tag}：未检出 {color} 光斑（面积 {result.area_px:.0f}px²/命中 "
            f"{result.pixel_count}）——检查相机对准、云台模式是否允许激光"
            f"（GMBL-0016 权限矩阵）或激光值是否低于检测下限（<g13）"
            f"{fail_hint}")
        log_manager.log_and_attach(
            f"{tag}: {color} 光斑在（面积={result.area_px:.0f}px²）",
            f"光斑判读 {tag}")
    else:
        results = {key: camera.detect_spot(frame, key)
                   for key in ("green", "blue")}
        found = [key for key, r in results.items() if r.found]
        allure.attach(encode_jpg(frame), name=f"光斑判读 {tag}",
                      attachment_type=allure.attachment_type.JPG)
        assert not found, (
            f"{tag}：预期熄灭但仍检出光斑: {found}（余辉/残留或误检）"
            f"{fail_hint}")
        log_manager.log_and_attach(f"{tag}: 绿/蓝均无光斑", f"光斑判读 {tag}")


# ============================================================================
# 测试类
# ============================================================================

@allure.feature("激光云台控制")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "LASER_GIMBAL", "GIMBAL_MODE")
@pytest.mark.functional
class TestMavlinkGimbal(_GimbalLaserBase):
    """X1 激光云台控制测试 — 云台模式/Lock 角度/通道匹配/激光限幅
    （GMBL 用例统一追加到本类）"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, drone_ip, drone_port, mavlink_version):
        """测试前置/后置（终端握手；后置兜底：关激光、归零、恢复 Init、
        关路由、关地面站）"""
        self.drone_ip = drone_ip
        self.drone_port = drone_port
        self.mavlink_version = mavlink_version

        try:
            with allure.step("打开终端（初始化地面站，打通 CONSOLE 通道）"):
                self.gcs = GroundControlStation(drone_ip=drone_ip, drone_port=drone_port)
                log_manager.log_and_attach(
                    f"地面站初始化完成，本地地址: {self.gcs.local_ip}:{self.gcs.local_port}",
                    "初始化信息")
                self._clear_recv_buffer()
                # 等一跳心跳（实测约 5s 一条，收到即返回）：登记 discovered
                # 集合消除 send() 的"未被发现"误告警，离线时留日志线索
                self._wait_drone_online()
                # 关键握手：SR0_CONSOLE 打开 CLI→CONSOLE 路由（恒定先复位
                # 再置 20，回显 Save/Set OK 必然出现，详见 _set_console_route）
                self._set_console_route(20.0)
                # 固件版本/SN 写入 allure 环境信息（对齐串口 fixture 归档口径）
                self._record_device_env()
        except Exception:
            # setup 失败时 pytest 不跑本 fixture 的 teardown，须自行关闭
            # 套接字，避免残留占住 14550 影响后续用例
            self.gcs.close()
            raise
        yield
        with allure.step("清理测试资源（关激光、归零、恢复 Init 模式、关路由、关闭终端）"):
            try:
                # 兜底顺序按物理依赖：关激光 → 归零 → 恢复模式 → 关路由
                # （路由关了清理命令发不出）→ 关资源；Lock 归零在未进
                # Debug 时为无害 no-op（calibration 同口径）
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)
                self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL)
                self._gimbal_restore_init()
            except Exception as e:
                log_manager.logger.warning(f"兜底清理命令发送失败: {e}")
            finally:
                try:
                    self._set_console_route(0.0)   # SR0_CONSOLE=0 关路由
                except Exception as e:
                    log_manager.logger.warning(f"关闭 CONSOLE 路由失败: {e}")
                self.gcs.close()
                log_manager.log_and_attach("地面站已关闭", "清理信息")

    # ==================================================================
    # 云台模式控制（X1-REQ-GMBL-0001 / X1-TC-GMBL-0001）
    # ==================================================================

    @pytest.mark.p1
    @allure.severity(allure.severity_level.NORMAL)
    @allure.story("云台模式控制")
    @allure.title("P1 X1-TC-GMBL-0001 云台模式切换综合：三模式切换 + 无效参数报错")
    def test_gimbal_mode_control_flow(self):
        """验证云台模式控制流程（AC-001 + AC-004）：沿单向状态机走一圈
        Init → Debug → LD Protection → Init，gimbal 0 触发 Init 切换；
        Debug 态注入无效参数回 "unknow gimbal cmd" 且状态不变（状态不变
        为行为探针旁证，直接证据缺口见模块 docstring「真机判据口径」★条目）"""
        # ── 步骤 1：gimbal 1 切至 Debug（已知模式基准）─────────────────
        # 单向切换 Init → Debug → LD Protection → Init：测试开始云台处于
        # Init（上电初始态，前序用例后置亦恢复 Init）
        with allure.step("1. gimbal 1 切至 Debug（已知模式，无效参数状态不变的判定基准）"):
            resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
            assert 'set gimbal to debug mode' in resp.lower(), \
                f"未进入 Debug 模式: {resp[:200]}"

        # ── 步骤 2/3：无效参数 → 回显命中 unknow 且不触发切换 ─────────
        # 判据方向与正常切换相反：unknow 是预期正向标记，"set gimbal to"
        # 出现即失败；gimbal 5=超范围数字、gimbal a=非数字各覆盖一类
        with allure.step("2. 发送 gimbal 5（超范围数字参数）"):
            resp = self._send_console_cmd("gimbal 5")
            low = resp.lower()
            assert 'unknow gimbal cmd' in low, \
                f"gimbal 5 未命中错误提示 'unknow gimbal cmd': {resp[:200]}"
            assert 'set gimbal to' not in low, \
                f"gimbal 5 无效参数不应触发模式切换: {resp[:200]}"

        with allure.step("3. 发送 gimbal a（非数字参数）"):
            resp = self._send_console_cmd("gimbal a")
            low = resp.lower()
            assert 'unknow gimbal cmd' in low, \
                f"gimbal a 未命中错误提示 'unknow gimbal cmd': {resp[:200]}"
            assert 'set gimbal to' not in low, \
                f"gimbal a 无效参数不应触发模式切换: {resp[:200]}"

        # ── 步骤 4：gimbal 2 切至 LD Protection ───────────────────────
        # 双重角色：走到 gimbal 0 的合法前驱；兼作行为探针——无效命令后
        # 合法切换仍正常回显，即状态未被破坏的旁证（两步间的无效命令
        # 即天然切换间隔；protobuf 抓包 / GLB_VAR 读取真机无手段，缺口
        # 口径见模块 docstring）
        with allure.step("4. gimbal 2 切至 LD Protection（gimbal 0 的合法前驱，兼作状态未变探针）"):
            resp = self._gimbal_mode(GIMBAL_MODE_LD_PROT)
            assert 'set gimbal to ld protection mode' in resp.lower(), \
                f"未进入 LD Protection 模式: {resp[:200]}"

        # ── 步骤 5：发送被测命令 gimbal 0 ─────────────────────────────
        with allure.step("5. 发送被测命令 gimbal 0"):
            resp = self._gimbal_mode(GIMBAL_MODE_INIT)

        # ── 步骤 6：验证 Init 模式回显 ────────────────────────────────
        # _gimbal_mode 内置正向+反向断言（方法层最低判据）；此处显式重申
        # 判据，报告可见（protobuf/GLB_VAR 无观测手段，口径见模块 docstring）
        with allure.step("6. 验证回显命中 'set gimbal to init mode' 且无失败标记"):
            assert 'set gimbal to init mode' in resp.lower(), \
                f"gimbal 0 未命中 Init 正向回显: {resp[:200]}"
            low = resp.lower()
            assert not any(marker in low for marker in ("nak", "unknow")), \
                f"gimbal 0 回显含失败标记: {resp[:200]}"

    # ==================================================================
    # 云台 Follow 模式角向量控制（X1-REQ-GMBL-0002 / X1-TC-GMBL-0002）
    # ==================================================================

    @pytest.mark.p1
    @allure.severity(allure.severity_level.NORMAL)
    @allure.story("云台 Follow 模式角向量控制")
    @allure.title("P1 X1-TC-GMBL-0002 Follow 模式角向量控制：向量映射与 ±50° 限位（AC-001~006）")
    def test_gimbal_vector_follow_control(self):
        """验证 Follow 模式角向量指令（183/param7=10）全流程（AC-001~006，
        单用例覆盖）：指令接受与向量遍历判 ACK result=0；UORB 字段赋值
        （AC-002/003）无观测手段，向量线性映射/正负方向（AC-005）与
        arcsin 换算到位、50° 饱和、0.766 临界值（AC-006）无遥测——
        人工观察（缺口口径见模块 docstring）；另含模式门控补充检查
        （切出 Debug 后向量不生效，超出库 AC，待真机验证）"""
        # ── 前置：切 Debug 并向量归零 ────────────────────────────────
        # Follow 向量在 Debug（CLI 手动）模式使用（X1-REQ-GMBL-0002 §4）
        with allure.step("前置：gimbal 1 切至 Debug，向量 (0,0,0) 起始基准"):
            resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
            assert 'set gimbal to debug mode' in resp.lower(), \
                f"未进入 Debug 模式: {resp[:200]}"
            self._gimbal_vector(0, 0, 0, channel=GIMBAL_CHANNEL, settle=2.0)

        # ── 步骤 1：基本三轴向量指令 ─────────────────────────────────
        # AC-001 指令正确接收；AC-002/003 UORB type/x/y/z/channel 字段
        # 赋值无监听手段；AC-004 按向量方向运动、三轴独立——人工观察
        # 缺口；通道取 3（真机云台所在通道，库用例按 HIL 台架写 param4=1）
        with allure.step("1. 归零 → 向量 (0.5, -0.3, 0.2)，三轴运动人工判读"):
            # 步前恢复默认位置（向量全 0 → 0°/0°）：每步从同一起始基准
            # 出发，动作幅度与方向可归因
            self._gimbal_vector(0, 0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            ack = self._gimbal_vector(0.5, -0.3, 0.2, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, \
                f"向量 (0.5,-0.3,0.2) 指令被拒绝: {ack.fields}"
            log_manager.log_and_attach(
                "人工判读点：云台应按向量方向和大小运动（三轴独立可控）",
                "人工观察")

        # ── 步骤 2：[-1,1] 三轴遍历（各轴步前归零、取值彼此错开）─────
        # AC-005 线性映射与正负方向；x 用库用例原值，y/z 另取错开值——
        # 三轴若用同一组值，观察者无法分辨动作来自哪一轴；z（Yaw）是否
        # 有执行机构未知，无动作如实记录不判失败（不死板 FAIL）
        with allure.step("2. 三轴遍历：x[-1,-0.5,0,0.5,1] / y[0.8,0.3,-0.6] / z[-0.9,0.4]，各轴步前归零"):
            with allure.step("2a. x 轴（Roll 向量）遍历"):
                self._gimbal_vector(0, 0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
                for v in (-1.0, -0.5, 0.0, 0.5, 1.0):
                    with allure.step(f"x={v}"):
                        ack = self._gimbal_vector(v, 0, 0, channel=GIMBAL_CHANNEL)
                        assert ack.fields.get('result', -1) == 0, \
                            f"x={v} 向量指令被拒绝: {ack.fields}"
            with allure.step("2b. y 轴（Pitch 向量）遍历（取值与 x/z 错开）"):
                self._gimbal_vector(0, 0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
                for v in (0.8, 0.3, -0.6):
                    with allure.step(f"y={v}"):
                        ack = self._gimbal_vector(0, v, 0, channel=GIMBAL_CHANNEL)
                        assert ack.fields.get('result', -1) == 0, \
                            f"y={v} 向量指令被拒绝: {ack.fields}"
            with allure.step("2c. z 轴（Yaw 向量）遍历（取值与 x/y 错开）"):
                self._gimbal_vector(0, 0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
                for v in (-0.9, 0.4):
                    with allure.step(f"z={v}"):
                        ack = self._gimbal_vector(0, 0, v, channel=GIMBAL_CHANNEL)
                        assert ack.fields.get('result', -1) == 0, \
                            f"z={v} 向量指令被拒绝: {ack.fields}"
            log_manager.log_and_attach(
                "人工判读点：x 由 -1→1 连续反向换向；y、z 各自按取值方向"
                "运动（三轴取值错开便于归因）；z（Yaw）若全程无动作，如实"
                "记录（云台仅 roll/pitch 两舵机时属预期，不判失败）",
                "人工观察")
        
        # ── 步骤 3：|v|=0.5 → arcsin(0.5)=30°，正常到达 ──────────────
        # AC-006 换算规则：舵机角=arcsin(单轴分量)，50° 限位对应
        # sin50°≈0.766（X1-REQ-GMBL-0002 §4）
        with allure.step("3. 归零 → x 轴 |v|=0.5（< 0.766），换算 30° 到位人工判读"):
            self._gimbal_vector(0, 0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            ack = self._gimbal_vector(0.5, 0, 0, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, \
                f"x=0.5 向量指令被拒绝: {ack.fields}"
            log_manager.log_and_attach(
                "人工判读点：x=0.5 换算舵机角 arcsin(0.5)=30°（< 50°），"
                "云台应正常到达 30° 附近", "人工观察")

        # ── 步骤 4：|v|=0.9（> sin50°≈0.766）→ 饱和 50° ─────────────
        with allure.step("4. 归零 → x 轴 |v|=0.9（> 0.766），饱和 50° 人工判读"):
            self._gimbal_vector(0, 0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            ack = self._gimbal_vector(0.9, 0, 0, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, \
                f"x=0.9 向量指令被拒绝: {ack.fields}"
            log_manager.log_and_attach(
                "人工判读点：x=0.9 对应角 > 50°，云台实际应饱和于 +50° "
                "限位不越界", "人工观察")

        # ── 步骤 5：|v|=0.766（sin50° 临界值）→ 恰 50° 边界 ──────────
        with allure.step("5. 归零 → x 轴 |v|=0.766（sin50° 临界值），恰 50° 边界人工判读"):
            self._gimbal_vector(0, 0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            ack = self._gimbal_vector(0.766, 0, 0, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, \
                f"x=0.766 临界向量指令被拒绝: {ack.fields}"
            log_manager.log_and_attach(
                "人工判读点：x=0.766 换算角恰为 50° 限位边界，云台到达但"
                "不越界（与步骤 4 饱和位同高）", "人工观察")
        
        # ── 恢复：向量归零 ────────────────────────────────────────────
        with allure.step("恢复：向量 (0,0,0) 归零"):
            self._gimbal_vector(0, 0, 0, channel=GIMBAL_CHANNEL, settle=2.0)

        # ── 步骤 6：非 Debug 模式下向量指令不生效（模式门控）─────────
        # 向量/Lock 控制仅在 Debug（CLI 手动）模式使用（X1-REQ-GMBL-0002
        # §4）——切出 Debug 后指令应不再生效。判据同负向用例口径：ACK
        # 仅记录（飞控层是否拒绝未知，result 不构成判据），云台无动作
        with allure.step("6. 模式门控：切出 Debug（LD Protection → Init）后向量指令不生效"):
            with allure.step("6a. gimbal 2 切至 LD Protection → 发向量 (0.5,0,0)，云台应无进一步动作"):
                resp = self._gimbal_mode(GIMBAL_MODE_LD_PROT)
                assert 'set gimbal to ld protection mode' in resp.lower(), \
                    f"未进入 LD Protection 模式: {resp[:200]}"
                # 切 LD Protection 触发收纳动作（2026-09-17 真机实测：落地
                # 保护即收纳，GMBL-0026 降落收纳策略同源）——等收纳走完
                # 再发向量，避免收纳动作被误归因给向量指令（归因隔离）
                time.sleep(3.0)
                # 直接 _send_command_long + expect_result=None：_gimbal_vector
                # 内置 ACK result=0 断言，而门控场景"被拒/被忽略"均属正确
                ack = self._send_command_long(
                    CMD_DO_SET_SERVO,
                    param1=0.5, param2=0, param3=0,   # x=0.5 → 换算 30°，幅度便于观察
                    param4=GIMBAL_CHANNEL, param7=10,
                    expect_result=None)
                log_manager.log_and_attach(
                    f"LD Protection 模式向量 ACK result="
                    f"{ack.fields.get('result')}（不判据）；人工判读点："
                    f"云台应无进一步动作（切 LD_PROT 自身的收纳动作不计）",
                    "人工观察")
                time.sleep(1.0)   # 无动作观察窗口

            with allure.step("6b. gimbal 0 切至 Init → 发向量 (0.5,0,0)，云台应无进一步动作"):
                resp = self._gimbal_mode(GIMBAL_MODE_INIT)
                assert 'set gimbal to init mode' in resp.lower(), \
                    f"未进入 Init 模式: {resp[:200]}"
                # Init 不触发运动（09-14「Init 不自动回中」+ 09-17 复核：
                # 收纳发生在途经的 LD_PROT 一步）——云台停在收纳位上，
                # 短间隔后直接发向量判读
                time.sleep(1.0)
                ack = self._send_command_long(
                    CMD_DO_SET_SERVO,
                    param1=0.5, param2=0, param3=0,
                    param4=GIMBAL_CHANNEL, param7=10,
                    expect_result=None)
                log_manager.log_and_attach(
                    f"Init 模式向量 ACK result={ack.fields.get('result')}"
                    f"（不判据）；人工判读点：收纳位上应无任何动作", "人工观察")
                time.sleep(1.0)   # 无动作观察窗口

            with allure.step("6c. 行为探针：gimbal 1 切回 Debug → 向量 (0.5,0,0) 应恢复生效"):
                resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
                assert 'set gimbal to debug mode' in resp.lower(), \
                    f"未切回 Debug 模式: {resp[:200]}"
                ack = self._gimbal_vector(0.5, 0, 0, channel=GIMBAL_CHANNEL)
                assert ack.fields.get('result', -1) == 0, \
                    f"探针向量指令被拒绝（Debug 下应正常生效）: {ack.fields}"
                log_manager.log_and_attach(
                    "人工判读点：云台应运动到 ~30°（旁证 6a/6b 无动作是"
                    "模式门控而非链路失效）", "人工观察")
                self._gimbal_vector(0, 0, 0, channel=GIMBAL_CHANNEL, settle=2.0)

    # ==================================================================
    # 云台 Lock 模式角度控制（X1-REQ-GMBL-0003 / X1-TC-GMBL-0003）
    # ==================================================================

    @pytest.mark.p1
    @allure.severity(allure.severity_level.NORMAL)
    @allure.story("云台 Lock 模式角度控制")
    @allure.title("P1 X1-TC-GMBL-0003 Lock 模式角度锁定综合：基本/边界/旧版指令/通道独立/机械限位（AC-001~008）")
    def test_gimbal_lock_angle_control_flow(self):
        """验证 Lock 模式指令（183/param7=11）全流程（AC-001~008，单用例
        覆盖；每步步前 Lock(0°,0°) 归零）：指令接受与边界判 ACK result=0；
        UORB 字段赋值（AC-002/003）无观测手段；到位锁定（AC-004）、饱和
        位置（AC-008）无遥测——人工观察；AC-006 旧版指令与 AC-007 错通道
        指令按负向口径判（ACK 仅记录 + 无动作人工观察，本通道正向步骤
        兼任链路完好判据）；多通道独立在单云台下以"发他通道、本通道未
        响应"间接验证（口径见模块 docstring）"""
        # ── 前置：切 Debug（Lock 模式在 Debug 模式使用，需求 §4）──────
        with allure.step("前置：gimbal 1 切至 Debug（Lock 模式在 Debug 模式使用）"):
            resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
            assert 'set gimbal to debug mode' in resp.lower(), \
                f"未进入 Debug 模式: {resp[:200]}"

        # ── 步骤 1：基本角度锁定指令 ──────────────────────────────────
        # AC-001 指令正确接收；AC-002/003 UORB 字段无监听手段；AC-004
        # 到位锁定无遥测（msg 8 仅 gimbal_version）——人工观察缺口
        with allure.step("1. 归零 → Lock(30°, -20°)，运动锁定人工判读"):
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            ack = self._gimbal_lock_angle(30, -20, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, \
                f"Lock(30°,-20°) 指令被拒绝: {ack.fields}"
            log_manager.log_and_attach(
                "人工判读点：云台应运动到 roll=30°/pitch=-20° 后锁定", "人工观察")

        # ── 步骤 2：[-180°,180°] 双向边界四发 ─────────────────────────
        # AC-005 边界值正常接受；>±50° 实际饱和于机械限位（见步骤 6/7），
        # 指令层面仍应 ACK result=0；组内一次归零，四发方向反转肉眼可辨
        with allure.step("2. 归零 → 边界四发 (±180°,0)/(0,±180°)，各 ACK result=0"):
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            for x_deg, y_deg in ((180, 0), (-180, 0), (0, 180), (0, -180)):
                with allure.step(f"Lock({x_deg}°, {y_deg}°)"):
                    ack = self._gimbal_lock_angle(x_deg, y_deg, channel=GIMBAL_CHANNEL)
                    assert ack.fields.get('result', -1) == 0, \
                        f"Lock({x_deg}°,{y_deg}°) 边界指令被拒绝: {ack.fields}"

        # ── 步骤 3：旧版指令 param7=5 不可达 ──────────────────────────
        # AC-006：旧版缺 channel 字段不能到达云台。取值来源
        # command_183_functions.json「云台角度」条目（param7=5,
        # yaw/roll/pitch，"不再使用"）；expect_result=None——被拒/被忽略
        # 均属不可用，result 不构成判据
        with allure.step("3. 归零 → 旧版指令 param7=5（yaw=30, roll=-20, pitch=0），云台应无动作"):
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            ack = self._send_command_long(
                CMD_DO_SET_SERVO,
                param1=30, param2=-20, param3=0,   # 旧版轴序 yaw/roll/pitch
                param4=GIMBAL_CHANNEL, param7=5,   # 旧版子命令（无 channel 语义）
                expect_result=None)
            log_manager.log_and_attach(
                f"旧版 param7=5 ACK result={ack.fields.get('result')}（不判据："
                f"被拒/被忽略均属不可用）；人工判读点：云台应无动作", "旧版指令响应")

        # ── 步骤 4：多通道独立（AC-007，单云台间接口径）───────────────
        # 库用例：通道 1 锁 10°、通道 2 锁 40° 各自独立互不干扰。真机仅
        # 通道 3 在线 → 间接验证：向他通道（1/2，沿用库取值）发锁定指令，
        # 本通道云台不应动（隔离即独立的单机可达判据）；两在线云台互不
        # 干扰的直接验证仍需多云台环境（缺口如实标注）
        with allure.step("4. 归零 → 他通道（1/2）各发锁定指令，本通道（3）应无响应"):
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            for ch, roll_deg in ((1, 10), (2, 40)):   # 库用例原值（通道1=10°/通道2=40°）
                with allure.step(f"通道 {ch} Lock({roll_deg}°, 0°) → 本通道云台应无动作"):
                    ack = self._send_command_long(
                        CMD_DO_SET_SERVO,
                        param1=roll_deg, param2=0,
                        param4=ch,        # 非本机通道（真机云台仅在通道 3）
                        param7=11,        # Lock 模式（新版）
                        expect_result=None)
                    log_manager.log_and_attach(
                        f"通道 {ch} 指令 ACK result={ack.fields.get('result')}"
                        f"（不判据：通道路由丢弃无回执差异）；人工判读点："
                        f"通道 3 云台应无动作", "错通道响应")

        # ── 步骤 5：本通道正常受控（AC-007 正向半边）──────────────────
        # 隔离之外还须本通道可控才算"独立"；此步同时是前面两条负向步骤
        # （旧版指令/错通道）之后的天然链路完好证据
        with allure.step("5. 本通道 Lock(40°, 0°) → ACK=0，云台正常锁定（通道独立旁证）"):
            ack = self._gimbal_lock_angle(40, 0, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, \
                f"本通道 Lock(40°,0°) 指令被拒绝（云台应在线可控）: {ack.fields}"
            log_manager.log_and_attach(
                "人工判读点：云台应运动到 roll=40°（他通道指令未影响本通道"
                "——单云台下的通道独立判据；多云台直接验证为环境缺口）",
                "人工观察")

        # ── 步骤 6：机械限位 roll=120°（> +50° 限位）──────────────────
        # AC-008：指令角度超限被接受（ACK=0），实际锁定饱和于 ±50°
        # 限位不越界；饱和位无遥测，人工判读
        with allure.step("6. 归零 → Lock(120°, 0°)（超 +50° 限位），饱和位人工判读"):
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            ack = self._gimbal_lock_angle(120, 0, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, \
                f"Lock(120°,0°) 指令被拒绝（指令应被接受）: {ack.fields}"
            log_manager.log_and_attach(
                "人工判读点：云台实际应锁定于 +50° 饱和位，不超出限位", "人工观察")

        # ── 步骤 7：机械限位 pitch=-90°（< -50° 限位）─────────────────
        with allure.step("7. 归零 → Lock(0°, -90°)（超 -50° 限位），饱和位人工判读"):
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            ack = self._gimbal_lock_angle(0, -90, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, \
                f"Lock(0°,-90°) 指令被拒绝（指令应被接受）: {ack.fields}"
            log_manager.log_and_attach(
                "人工判读点：云台实际应锁定于 -50° 饱和位，不超出限位", "人工观察")

        # ── 恢复：归零 ────────────────────────────────────────────────
        with allure.step("恢复：Lock(0°, 0°) 归零"):
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=2.0)

    # ==================================================================
    # 通道匹配与上电识别（X1-REQ-GMBL-0004 / X1-TC-GMBL-0004）
    # ==================================================================

    @pytest.mark.p1
    @allure.severity(allure.severity_level.NORMAL)
    @allure.story("通道匹配与上电识别")
    @allure.title("P1 X1-TC-GMBL-0004 通道匹配与上电识别综合：匹配规则/广播激光/ADC 缺位（AC-001~006）")
    def test_gimbal_channel_match_flow(self):
        """验证通道匹配规则与上电识别条件（AC-001~006，单用例覆盖）。
        ⚠ 判据弱化声明（真机无观测手段，打开用例先看这里）：
        - AC-001 通道匹配：错通道指令"被丢弃"无回执差异 → 弱化为 ACK
          仅记录 + 本通道无动作人工观察 + 本通道行为探针
        - AC-002 通道号与挂载位置：仅弱旁证（本通道 3 可控，与上视挂载
          组 1/3 一致）；上电 ADC 识别门限/初始化/卸载时序（AC-002~004/
          006）真机无注入与观测手段 → 步骤内缺位说明，不装能验
        - AC-005 广播"全部云台同时受控"：单云台只能验证在线云台生效
          （多云台缺口）；亮灭无遥测（laser_state 是温度告警码）→ 人工
          观察"""
        # ── 前置：切 Debug 并归零 ─────────────────────────────────────
        with allure.step("前置：gimbal 1 切至 Debug，Lock(0°, 0°) 起始基准"):
            resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
            assert 'set gimbal to debug mode' in resp.lower(), \
                f"未进入 Debug 模式: {resp[:200]}"
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=2.0)

        # ── 步骤 1：向非本机通道 1 发指令 ─────────────────────────────
        # 真机云台在通道 3（conftest 口径），通道 1 无云台 → 指令应被
        # 丢弃；FC 层 ACK 可能照回 result=0（通道路由丢弃在下游），
        # expect_result=None 仅记录，判据=云台无动作（人工观察）
        with allure.step("1. 向非本机通道 1 发 Lock(30°, -20°) → 云台应无动作"):
            ack = self._send_command_long(
                CMD_DO_SET_SERVO,
                param1=30, param2=-20,
                param4=1,        # 非本机通道（真机云台在通道 3）
                param7=11,       # Lock 模式（新版）
                expect_result=None)
            log_manager.log_and_attach(
                f"通道 1 指令 ACK result={ack.fields.get('result')}（不判据："
                f"通道路由丢弃无回执差异）；人工判读点：云台应无动作", "错通道响应")

        # ── 步骤 2：本通道行为探针 + AC-002 弱旁证 ────────────────────
        # 旁证在线通道=3；上视挂载组为 1/3（GMBL-0004 §1），与实测通道
        # 一致 → AC-002（通道号与挂载位置一致）的弱旁证；若未来通道 1
        # 挂载云台，步骤 1 的"无动作"前提失效，本用例需改错通道取值
        with allure.step("2. 行为探针：向本机通道 3 发 Lock(30°, -20°) → ACK=0"):
            ack = self._gimbal_lock_angle(30, -20, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, \
                f"本机通道 3 指令被拒绝（云台应在线可控）: {ack.fields}"
            log_manager.log_and_attach(
                "人工判读点：云台应运动到 roll=30°/pitch=-20°（旁证在线通道=3，"
                "与上视挂载组 1/3 一致 → AC-002 弱旁证）", "人工观察")

        # ── 步骤 3：广播点亮绿色激光 ──────────────────────────────────
        # AC-005：channel=128 对全部在线云台生效；g=3 在护眼限幅 25 内
        # （calibration 同档亮度）；亮灭无遥测，人工判读
        with allure.step("3. 广播 128 点亮绿色激光 g=3 → ACK result=0"):
            ack = self._laser_color(3, 0, channel=LASER_BROADCAST_CHANNEL)
            assert ack.fields.get('result', -1) == 0, \
                f"广播点亮激光指令被拒绝: {ack.fields}"
            log_manager.log_and_attach(
                "人工判读点：激光应点亮（绿光）", "人工观察")
            time.sleep(1.0)   # 点亮观察窗口

        # ── 步骤 4：广播关闭激光 ──────────────────────────────────────
        with allure.step("4. 广播 128 关闭激光 (g/b=0) → ACK result=0"):
            ack = self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)
            assert ack.fields.get('result', -1) == 0, \
                f"广播关闭激光指令被拒绝: {ack.fields}"
            log_manager.log_and_attach(
                "人工判读点：激光应熄灭", "人工观察")

        # ── 步骤 5：上电 ADC 识别与初始化/卸载时序 —— 环境缺位说明 ────
        # AC-002~004/006：ADC 电压注入（150~450mV 门限内外上电）与
        # create_payload→init→on_power_on 时序监听需 HIL 台架，真机无
        # 注入与观测手段；真机旁证=通道 3 指令有效（步骤 2）。步骤内
        # 缺位说明，不 skip 整条用例
        with allure.step("5. 上电 ADC 识别与初始化/卸载时序（AC-002~004/006）— HIL 台架项缺位说明"):
            log_manager.log_and_attach(
                "AC-002~004/006（ADC 150~450mV 识别门限、create_payload→init"
                "→on_power_on→reg_task→start 时序、uninstall_can 卸载清理）"
                "需可调 ADC 电压源+时序监听，真机无注入与观测手段——本步骤"
                "仅缺位说明，不装能验；真机旁证：通道 3 指令有效（步骤 2）。"
                "待 HIL 台架补全", "验证缺位")

        # ── 恢复：归零 ────────────────────────────────────────────────
        with allure.step("恢复：Lock(0°, 0°) 归零"):
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=2.0)

    # ==================================================================
    # 激光功率限幅保护（X1-REQ-GMBL-0005 / X1-TC-GMBL-0005，危险·双层门控）
    # ==================================================================

    @pytest.mark.p0
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.story("激光功率限幅保护")
    @allure.title("P0 X1-TC-GMBL-0005 上锁激光功率限幅综合：DISARMED 限幅 + 解锁无残留（AC-001~004，相机判亮度·保守值·危险双层门控）")
    @armed_full_power_gate
    @laser_overdrive_gate
    def test_laser_power_clamp_flow(self):
        """验证上锁限幅与解锁无残留全流程（AC-001~004，单用例覆盖）。
        ⚠ 判据弱化声明（打开用例先看这里）：
        - 云台接收值（线上值）无遥测 → 判据以**相机量化亮度**为代理：
          固定手动曝光 -9 下，绿色光斑掩码命中像素数随激光功率单调增
          （blink 实测口径）。限幅生效 = 上锁态 g=64 与 g=25 亮度同档；
          不误限幅 = g=13 明显更暗；无残留 = 解锁态 g=64 明显亮于上锁
          态 g=64。★比值阈值初值待真机首跑校准定稿
        - AC-003 范围保持（接收值 0~255）完全不可验 → 判据仅 ACK
        - armed 前置/翻转以 packed_state 回读为准（解锁 ACK result=0
          存在假成功——X1 口径铁律）
        - 相机为可选外设：打开失败时判据降级为 ACK + 人工观察（不 fail）
        ⚠ 数值保守口径：最大请求只到 25%（g=64）——限幅失效时最大 25%
        输出，验证">10% 被钳"即足以证明限幅存在；满功率（255）验证留待
        CAN 抓包/遥测观测手段后补。本用例有意发超限值（绕过 _laser_color
        护眼守卫）；解锁段真解锁，台架前提见模块 docstring「危险门控」
        （拆桨+限流电源；限流致 ~5s 自动落锁时需先 CLI sp FS_BATT_ACT: 0，
        试飞前恢复 1——GCS-03 口径）"""
        #  $env:GMBL_ENABLE_LASER_OVERDRIVE = "1"
        #  $env:GMBL_ENABLE_ARMED_FULL_POWER = "1"
        # 亮度比值阈值（★初值，待真机首跑校准定稿——失败先看测量值
        # 是否档位分明，再调阈值而非直接放行）
        same_level_ratio = 1.5   # 限幅判据：上锁态 g=64/g=25 命中像素比 ≤ 此值
        release_ratio = 1.5      # 解锁判据：解锁态/上锁态 g=64 命中像素比 ≥ 此值

        # 护眼限幅上限用例内覆盖到 64（保守上限）：授权来自装饰器门控；
        # 仍走 _laser_color 统一发送通路——守卫继续生效，>64 的误发
        # （如 255 手滑）会被拦截。pytest 每用例新实例，覆盖不外泄到
        # 其他用例（其余用例维持 25）
        self.LASER_POWER_LIMIT = 64

        def request_packed_state(timeout=4.0, retries=2):
            """发一次 heartbeat_dmd 并等待 packed_state 回传（GCS-02 请求-
            回传机制；帧取自 fc_basic_base.HEARTBEAT_DMD_HEX，真机验证
            可用帧）。嵌套函数：仅本用例消费（sweep_path 先例），不进
            conftest。返回 packed_state 消息，超时返回 None。"""
            for _ in range(retries):
                self.gcs.send(MAVLink_message(hex_data=HEARTBEAT_DMD_HEX),
                              addr=(self.drone_ip, self.drone_port))
                start = time.time()
                while time.time() - start < timeout:
                    received, addr = self.gcs.receive()
                    if (received is not None
                            and received.msg_id == MSG_ID_PACKED_STATE
                            and addr and addr[0] == self.drone_ip):
                        return received
                    time.sleep(0.02)
            return None

        def poll_armed(expected, timeout=5.0):
            """轮询 packed_state.armed 至期望值（容忍业务层传播延迟）；
            超时返回 None（不抛断言）——调用点决定失败处理（附 dmsg 原因）"""
            deadline = time.time() + timeout
            while time.time() < deadline:
                packed = request_packed_state(timeout=2.0, retries=1)
                if packed is not None and packed.fields.get('armed') == expected:
                    return packed
                time.sleep(0.5)
            return None

        def measure_green_spot(tag):
            """取图测绿色光斑亮度，返回掩码命中像素数（相机不可用返回
            None，判据降级人工）。画面与测量值进报告。"""
            if camera is None:
                log_manager.log_and_attach(
                    f"{tag}：相机不可用，亮度判读降级为人工观察",
                    f"亮度测量 {tag}")
                return None
            time.sleep(0.3)   # 光斑稳定 + 曝光适应
            frame = camera.capture()
            result = camera.detect_spot(frame, "green")
            allure.attach(encode_jpg(camera.annotate(frame, result)),
                          name=f"亮度测量 {tag}",
                          attachment_type=allure.attachment_type.JPG)
            assert result.found, (
                f"{tag}：未检出绿色光斑（面积 {result.area_px:.0f}px²/命中 "
                f"{result.pixel_count}）——检查相机是否对准墙面光斑、云台是否"
                f"在 Debug 模式（INIT 禁止激光输出，GMBL-0016）")
            log_manager.log_and_attach(
                f"{tag}: 命中像素={result.pixel_count}, "
                f"面积={result.area_px:.0f}px²", f"亮度测量 {tag}")
            return result.pixel_count

        # ── 前置：上锁实锤 + Debug（激光输出权限）+ 开相机 ──────────────
        with allure.step("前置：确认上锁态，gimbal 1 切 Debug（激光输出权限），打开相机"):
            packed0 = request_packed_state()
            assert packed0 is not None, "无法获取 packed_state（heartbeat_dmd 无回传）"
            initial_mode = packed0.fields.get('mode')
            armed0 = packed0.fields.get('armed')
            if armed0 == 1:
                # 已处解锁态（异常残留）→ 先上锁归位；重复上锁可能幂等
                # 拒绝，不判 ACK 只看 armed 回读
                self._send_command_long(CMD_ARM_DISARM, param1=DISARM_P1,
                                        expect_result=None)
                assert poll_armed(0, timeout=5.0) is not None, \
                    "初始上锁（归位）失败：armed 未回 0"
            log_manager.log_and_attach(
                f"packed_state.armed={armed0}（归位后上锁态实锤）、"
                f"initial_mode={initial_mode}", "前置确认")
            # Debug 模式才有激光输出权限（GMBL-0016 权限矩阵：INIT 禁止
            # 激光输出）——不切 Debug 相机看不到光
            resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
            assert 'set gimbal to debug mode' in resp.lower(), \
                f"未进入 Debug 模式: {resp[:200]}"
            # 相机可选外设（手动曝光 -9——自动曝光会把亮度洗平，量化前提
            # 是固定曝光）；按设备名打开 FF-Camera——DirectShow 索引顺序
            # 会随插拔漂移（09-15 时 FF 在 index 1、09-17 漂到 0，硬编码
            # index 开到过 Integrated Camera 黑帧），名字解析见 laser_camera
            camera = None
            try:
                camera = LaserSpotCamera(camera_name="FF-Camera",
                                         width=1920, height=1080,
                                         exposure=-9).open()
                log_manager.log_and_attach(
                    f"相机已打开 FF-Camera（index={camera.camera_index}，"
                    f"曝光 -9）", "前置确认")
            except Exception as e:
                log_manager.logger.warning(f"相机打开失败，亮度判读降级人工: {e}")
            self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)   # 起始暗态

        # try 覆盖步骤 1 起（而非仅解锁段）：相机已在前置打开，任何步骤
        # 失败都必须走 finally 关激光/关相机——否则进程带相机退出会把
        # FF-Camera 的 DirectShow 过滤器卡死（2026-09-17 实锤：步骤 5
        # 失败未关相机，之后 DSHOW 再也打不开，只能重插解卡）
        try:
            # ── 步骤 1：上锁态 g=64（25%，超 10% 门限）─────────────────
            # AC-001：预期被钳到 ≈25 → 亮度应与步骤 2 的 g=25 同档
            with allure.step("1. 上锁态请求 25%（g=64，超门限）→ ACK=0，相机测亮度"):
                ack = self._send_command_long(
                    CMD_DO_SET_SERVO,
                    param2=64, param3=0,    # 绿光 g=64（25%，保守上限）
                    param4=LASER_BROADCAST_CHANNEL, param7=4)
                assert ack.fields.get('result', -1) == 0, \
                    f"上锁态 g=64 指令被拒绝: {ack.fields}"
                px64_disarmed = measure_green_spot("上锁态 g=64")

            # ── 步骤 2：上锁态 g=25（恰 10% 门限，原值）──────────────
            # AC-002 基准档：门限值不误限幅、原值下发
            with allure.step("2. 上锁态请求恰 10%（g=25，门限边界原值）→ ACK=0，相机测亮度"):
                ack = self._send_command_long(
                    CMD_DO_SET_SERVO,
                    param2=25, param3=0,
                    param4=LASER_BROADCAST_CHANNEL, param7=4)
                assert ack.fields.get('result', -1) == 0, \
                    f"上锁态 g=25 指令被拒绝: {ack.fields}"
                px25_disarmed = measure_green_spot("上锁态 g=25")

            # ── 步骤 3：上锁态 g=13（5%，低于门限，原值）──────────────
            # AC-002：未超门限按原值下发 → 应明显更暗
            with allure.step("3. 上锁态请求 5%（g=13，低于门限）→ ACK=0，相机测亮度"):
                ack = self._send_command_long(
                    CMD_DO_SET_SERVO,
                    param2=13, param3=0,
                    param4=LASER_BROADCAST_CHANNEL, param7=4)
                assert ack.fields.get('result', -1) == 0, \
                    f"上锁态 g=13 指令被拒绝: {ack.fields}"
                px13_disarmed = measure_green_spot("上锁态 g=13")

            # ── 步骤 4：限幅判读（相机量化断言）────────────────────────
            # g=64 被钳到 ≤25 → 与 g=25 同档；g=13 原值 → 严格更暗。相机
            # 不可用时降级人工判读（不 fail）
            with allure.step("4. 限幅判读：g=64 与 g=25 亮度同档，g=13 更暗"):
                if None in (px64_disarmed, px25_disarmed, px13_disarmed):
                    log_manager.log_and_attach(
                        "相机不可用，AC-001/002 亮度判据降级人工观察：g=64 应"
                        " 与 g=25 无明显差异（限幅生效）、g=13 应明显更暗"
                        "（不误限幅）", "人工判读")
                else:
                    assert px64_disarmed <= px25_disarmed * same_level_ratio, (
                        f"AC-001 限幅未生效嫌疑：上锁态 g=64 命中像素 "
                        f"{px64_disarmed} 明显高于 g=25 的 {px25_disarmed}"
                        f"（比值 {px64_disarmed / px25_disarmed:.2f} > "
                        f"{same_level_ratio}）——g=64 疑似未被钳到 ≈25；"
                        f"★阈值待校准，档位分明时可调")
                    assert px13_disarmed < px25_disarmed, (
                        f"AC-002 疑似误限幅或相机档位不敏感：g=13 命中像素 "
                        f"{px13_disarmed} 未低于 g=25 的 {px25_disarmed}"
                        f"（应原值下发更暗）；★阈值待校准")
                    log_manager.log_and_attach(
                        f"限幅判读通过：g=64/g=25="
                        f"{px64_disarmed / px25_disarmed:.2f}（同档，被钳 ≈25）、"
                        f"g=13/g=25={px13_disarmed / px25_disarmed:.2f}"
                        f"（更暗，原值）", "限幅判读")

            # ── 步骤 5：上锁态扫描 → 接受范围保持 ──────────────────────
            # AC-003 云台接收值始终 0~255——接收值无遥测不可验，判据仅
            # ACK；扫描上限保守到 64（熄灭佐证在步骤 6 关光后做——扫描
            # 止于 g=64，激光仍亮着，此处验熄灭必挂，2026-09-17 实锤）
            with allure.step("5. 上锁态扫描 0%/5%/10%/25%（g=0/13/25/64）→ 各 ACK=0"):
                for g_value in (0, 13, 25, 64):
                    with allure.step(f"g={g_value}"):
                        ack = self._send_command_long(
                            CMD_DO_SET_SERVO,
                            param2=g_value, param3=0,
                            param4=LASER_BROADCAST_CHANNEL, param7=4)
                        assert ack.fields.get('result', -1) == 0, \
                            f"上锁态 g={g_value} 扫描指令被拒绝: {ack.fields}"
                    time.sleep(0.5)
                log_manager.log_and_attach(
                    "AC-003 范围保持（云台接收值 0~255）无遥测不可自动验证——"
                    "判据仅 ACK；如需定量需 CAN 抓包/功率计", "验证缺口")

            # ── 步骤 6：关激光 + 熄灭佐证（解锁段前安全位）─────────────
            # 保持"解锁前必关光"纪律：高亮度点亮只发生在步骤 9 受控窗口
            with allure.step("6. 关闭激光（解锁段前安全位）→ 相机验证熄灭"):
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)
                if camera is not None:
                    time.sleep(0.3)   # 熄灭静置
                    frame = camera.capture()
                    result = camera.detect_spot(frame, "green")
                    assert not result.found, (
                        f"关激光后仍检出绿色光斑（余辉/残留或误检）: "
                        f"面积={result.area_px:.0f}px²")
                    allure.attach(encode_jpg(frame), name="关激光后画面",
                                  attachment_type=allure.attachment_type.JPG)
            # ── 步骤 7：切 mode=4（play，解锁前置）────────────────────
            # SET_MODE(msg 11)：base_mode=0、target_system=1（GCS-03/GCS-05
            # 口径）；恢复段恢复初始模式同款字面展开
            with allure.step("7. SET_MODE 切 mode=4（play，解锁前置——GCS-03 口径）"):
                self.gcs.send(MAVLink_message(
                    msg_id=MSG_ID_SET_MODE, sys_id=1, comp_id=1, seq=0,
                    version=self.mavlink_version,
                    fields={'custom_mode': 4, 'target_system': 1, 'base_mode': 0}),
                    addr=(self.drone_ip, self.drone_port))
                time.sleep(2.0)   # 模式整定（fc_basic_base.SETTLE_MODE 同款）
                packed_mode = request_packed_state()
                mode_now = packed_mode.fields.get('mode') if packed_mode else None
                assert mode_now == 4, (
                    f"切表演模式(4)后 mode={mode_now}——模式切换未生效，"
                    f"解锁将被拒（'Mode cannot Arm'）")

            # ── 步骤 8：指令解锁 → armed 翻 1 ─────────────────────────
            # ⚠ ACK result=0 仅代表业务转发成功——拒绝时照样回 0，
            # armed 回读翻转才是执行实锤（X1 口径铁律）
            with allure.step("8. 指令解锁（cmd400 p1=1）→ packed_state.armed 翻 1"):
                self._send_command_long(CMD_ARM_DISARM, param1=ARM_P1)
                packed_armed = poll_armed(1, timeout=5.0)
                if packed_armed is None:
                    dmsg_tail = self._send_console_cmd("dmsg", timeout=8.0)[-500:]
                    assert False, (
                        f"ACK result=0 但 armed 未翻转为 1——解锁被拒或未执行。"
                        f"dmsg 尾部（拒绝/落锁原因）:\n{dmsg_tail}")
                log_manager.log_and_attach("armed=1（解锁实锤帧）", "解锁确认")

            # ── 步骤 9：解锁态 g=64 → 限幅解除（AC-004）────────────────
            # 解锁后同一 g=64 应按原值输出 → 明显亮于上锁态被钳的 g=64
            with allure.step("9. 解锁态请求 25%（g=64）→ 限幅解除，亮度应明显高于上锁态同值"):
                ack = self._send_command_long(
                    CMD_DO_SET_SERVO,
                    param2=64, param3=0,
                    param4=LASER_BROADCAST_CHANNEL, param7=4)
                assert ack.fields.get('result', -1) == 0, \
                    f"解锁态 g=64 指令被拒绝: {ack.fields}"
                px64_armed = measure_green_spot("解锁态 g=64")
                if px64_armed is not None and px64_disarmed is not None:
                    assert px64_armed >= px64_disarmed * release_ratio, (
                        f"AC-004 限幅残留嫌疑：解锁态 g=64 命中像素 {px64_armed} "
                        f"未明显高于上锁态 {px64_disarmed}（比值 "
                        f"{px64_armed / px64_disarmed:.2f} < {release_ratio}）——"
                        f"解锁后疑似仍被钳；★阈值待校准")
                    log_manager.log_and_attach(
                        f"限幅解除判读通过：解锁态/上锁态 g=64="
                        f"{px64_armed / px64_disarmed:.2f}", "限幅判读")
                else:
                    log_manager.log_and_attach(
                        "相机不可用，AC-004 亮度判据降级人工观察：解锁态 g=64 "
                        "应明显亮于上锁态同值（无限幅残留）", "人工判读")
                # 解锁保持复查：台架限流电源 ~5s 自动落锁鉴别（环境因素不
                # 计固件缺陷，GCS-03 口径），dmsg 尾部佐证
                if poll_armed(1, timeout=2.0) is None:
                    dmsg_tail = self._send_console_cmd("dmsg", timeout=8.0)[-500:]
                    log_manager.log_and_attach(
                        f"⚠ 观察窗口后 armed 已回锁——若 dmsg 为低电压/"
                        f"failsafe 属台架环境因素（GCS-03 口径）。"
                        f"dmsg 尾部:\n{dmsg_tail}", "保持性观察")

            # ── 步骤 10：解锁态低值 5% → 原值下发 ──────────────────────
            with allure.step("10. 解锁态请求 5%（g=13）→ 按原值正常下发"):
                ack = self._send_command_long(
                    CMD_DO_SET_SERVO,
                    param2=13, param3=0,
                    param4=LASER_BROADCAST_CHANNEL, param7=4)
                assert ack.fields.get('result', -1) == 0, \
                    f"解锁态 g=13 指令被拒绝: {ack.fields}"
                px13_armed = measure_green_spot("解锁态 g=13")
                if px13_armed is not None and px64_armed is not None:
                    log_manager.log_and_attach(
                        f"解锁态次序记录：g=13/g=64={px13_armed / px64_armed:.2f}"
                        f"（应 <1，低值更暗；仅记录不判据，★待校准）", "次序记录")
        finally:
            # ── 恢复：关激光 → 关相机 → 上锁 → 恢复初始模式 ────────────
            # 用例中途异常也须走完（finally）；重复上锁可能幂等拒绝
            # （GCS-03 待办项），清理段不判 ACK、以 armed 回读为准
            with allure.step("恢复：关激光 → 关相机 → 上锁（armed 回 0）→ 恢复初始模式"):
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)
                if camera is not None:
                    camera.close()
                    log_manager.log_and_attach("相机已关闭", "清理信息")
                self._send_command_long(CMD_ARM_DISARM, param1=DISARM_P1,
                                        expect_result=None)
                if poll_armed(0, timeout=5.0) is None:
                    log_manager.logger.warning("上锁后 armed 未回 0，人工核查")
                if initial_mode is not None and initial_mode != 4:
                    self.gcs.send(MAVLink_message(
                        msg_id=MSG_ID_SET_MODE, sys_id=1, comp_id=1, seq=0,
                        version=self.mavlink_version,
                        fields={'custom_mode': initial_mode, 'target_system': 1,
                                'base_mode': 0}),
                        addr=(self.drone_ip, self.drone_port))
                    time.sleep(2.0)   # 模式整定（同步骤 7）
                    log_manager.log_and_attach(
                        f"已恢复初始模式 mode={initial_mode}", "模式恢复")

    # ==================================================================
    # 高度保护（X1-REQ-GMBL-0006 / X1-TC-GMBL-0006，HIL/试飞占位）
    # ==================================================================

    @pytest.mark.p0
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.story("激光高度保护")
    @allure.title("P0 X1-TC-GMBL-0006 高度低于 20m 激光关闭保护（AC-001~004，HIL/试飞占位）")
    def test_laser_low_altitude_protection(self):
        """验证高度低于 20m 双通道置 0 + 关激光供电、≤1s 响应与恢复
        （AC-001~004）——高度触发需 HIL 假飞机注入 pos_z 或真机飞行穿越
        20m 门限；真机台架高度恒 ≈0m（低于门限）而 Debug 通路激光可正常
        点亮（2026-09-14 标定/blink 真机实测先例），说明保护链路在该通路
        不可达或未启用（或仅约束表演状态机 READY 流程），台架无法区分
        判定；响应时序 ≤1s 需示波器/时标。待 HIL 台架或试飞环境补全"""
        pytest.skip("高度触发需 HIL 假飞机注入 pos_z（如 -15m 触发/-20m 边界/"
                    "25m 恢复）或真机飞行 >20m 往返；台架 Debug 通路激光可点亮"
                    "（标定实测）说明保护在该通路不可达，无法台架判定；"
                    "响应时序 ≤1s 亦需示波器/时标——待 HIL/试飞环境补全")

    # ==================================================================
    # 飞机异常禁止激光（X1-REQ-GMBL-0007 / X1-TC-GMBL-0007，P0）
    # ==================================================================

    @pytest.mark.p0
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.story("激光异常保护")
    @allure.title("P0 X1-TC-GMBL-0007 飞机异常禁止激光输出：failsafe/非 GUIDED（真机=Debug 豁免探针+主体缺位）")
    def test_laser_failsafe_guard(self):
        """验证飞机异常（failsafe/非 GUIDED）禁止激光输出（AC-001~004，
        单用例覆盖）。
        ⚠ 判据弱化声明（打开用例先看这里）：
        - AC-001/002 主体不可达：需求限定"**非 DEBUG 模式**下发生
          failsafe 即关激光"，非 DEBUG 的激光输出态 = READY（解锁且
          高度 >20m，GMBL-0016/0034）→ 真机需飞行，台架不可达 →
          步骤 4 缺位说明，待试飞/HIL 补全
        - 本用例真机可跑部分为 **Debug 豁免探针**：Debug 模式下注入
          failsafe / 切非 GUIDED 模式，按需求字面激光应**保持输出**
          （调试态豁免，★推定待真机验证）——若激光被关 = 豁免不成立，
          与需求字面矛盾，记问题单；判据 = 相机光斑存在性（相机不可用
          时降级人工观察）
        - AC-003（云台不自行推断状态）为云台固件内部行为、AC-004
          （清零帧按需补发）需报文监听 → 均缺位
        - ffs 注入档位覆盖 battery/wp/fence/ekf/crash 五类（CLI 实测
          口径，GCS-04），radio/gcs/igniter 三类无注入命令（随主体缺位）"""
        with allure.step("前置：相机（按名 FF-Camera），gimbal 1 切 Debug，点亮绿激光 g=13"):
            # 相机可选外设（按名打开+手动曝光 -9，口径见 0005）；失败仅
            # 告警降级人工观察
            camera = None
            try:
                camera = LaserSpotCamera(camera_name="FF-Camera",
                                         width=1920, height=1080,
                                         exposure=-9).open()
            except Exception as e:
                log_manager.logger.warning(f"相机打开失败，豁免探针降级人工观察: {e}")
            resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
            assert 'set gimbal to debug mode' in resp.lower(), \
                f"未进入 Debug 模式: {resp[:200]}"
            # g=13：0005 同 setup 实测 962px 命中的稳妥值。g=3 实锤漏检
            # （2026-09-17：光斑核心过曝发白 → S<80 被绿色掩码排除、
            # 光环低于 V≥200，31px 散点不成轮廓）——小值光斑会因核心
            # 饱和掉出 HSV 掩码，勿再往下调
            self._laser_color(13, 0, channel=LASER_BROADCAST_CHANNEL)

        def spot_still_on(tag):
            """豁免探针判据：光斑仍存在（复用模块级 _verify_spot，相机
            不可用降级人工提示；豁免矛盾语义随 fail_hint 带入失败消息）"""
            _verify_spot(
                camera, "green", True, f"豁免探针 {tag}",
                fail_hint="——Debug 下激光被关与需求「非 DEBUG 才关激光」"
                          "字面矛盾（豁免不成立），记问题单核对")

        try:
            # ── 步骤 1：Debug 态基线——光斑在 ─────────────────────────
            with allure.step("1. Debug 态基线：相机确认光斑存在"):
                spot_still_on("基线")

            # ── 步骤 2：逐档注入 failsafe → 激光应保持 ────────────────
            # CLI ffs 档位（GCS-04 真机实锤，Fake 回显判据）：
            # 1=低电 2=航点失败 3=围栏 4,1,0,1=EKF 5=坠机；每档验毕即
            # ffs 0 清除（固件静默无回显）
            with allure.step("2. 逐档注入 failsafe（低电/航点/围栏/EKF/坠机）→ Debug 下激光保持"):
                for ffs_cmd, echo in (("1", "fake low battery"),
                                      ("2", "fake wp error"),
                                      ("3", "fake fence error"),
                                      ("4,1,0,1", "fake ekf"),
                                      ("5", "fake crash (fall)")):
                    with allure.step(f"ffs {ffs_cmd}"):
                        resp = self._send_console_cmd(f"ffs {ffs_cmd}")
                        assert echo in resp.lower(), \
                            f"ffs {ffs_cmd} 未命中回显 '{echo}': {resp[:200]}"
                        spot_still_on(f"ffs {ffs_cmd} 态")
                        self._send_console_cmd("ffs 0")   # 清除（静默无回显）
                        time.sleep(0.5)

            # ── 步骤 3：Debug 态切非 GUIDED（LOITER）→ 激光应保持 ────
            # SET_MODE(11) LOITER=5（GCS-05 枚举实锤；GUIDED=mode 4）；
            # 验毕切回 4（play/GUIDED 表演常态，GCS-03 解锁前置同款）
            with allure.step("3. SET_MODE 切 LOITER(5)（非 GUIDED）→ Debug 下激光保持"):
                self.gcs.send(MAVLink_message(
                    msg_id=11, sys_id=1, comp_id=1, seq=0,   # SET_MODE
                    version=self.mavlink_version,
                    fields={'custom_mode': 5, 'target_system': 1, 'base_mode': 0}),
                    addr=(self.drone_ip, self.drone_port))
                time.sleep(2.0)   # 模式整定（fc_basic_base.SETTLE_MODE 同款）
                spot_still_on("LOITER 态")
                self.gcs.send(MAVLink_message(
                    msg_id=11, sys_id=1, comp_id=1, seq=0,
                    version=self.mavlink_version,
                    fields={'custom_mode': 4, 'target_system': 1, 'base_mode': 0}),
                    addr=(self.drone_ip, self.drone_port))
                time.sleep(1.0)

            # ── 步骤 4：主体缺位说明 ──────────────────────────────────
            with allure.step("4. 主体缺位说明：非 DEBUG（READY）态的 failsafe/非 GUIDED 关激光待试飞/HIL"):
                log_manager.log_and_attach(
                    "AC-001/002 主体（非 DEBUG 态 failsafe/非 GUIDED 关闭激光）"
                    "需 READY 激光输出态（解锁且高度>20m，GMBL-0016/0034）——"
                    "真机需飞行，台架不可达；AC-003（云台不推断状态）为云台"
                    "固件内部行为、AC-004（清零帧按需补发）需报文监听；"
                    "radio/gcs/igniter 三类 failsafe 无 CLI 注入命令。"
                    "待试飞/HIL 台架补全", "验证缺位")
        finally:
            # 任何步骤失败都须关激光/关相机/清注入（相机泄漏教训见 0005）
            with allure.step("恢复：关激光 → ffs 0 清残留注入 → 关相机"):
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)
                self._send_console_cmd("ffs 0")
                if camera is not None:
                    camera.close()

    # ==================================================================
    # 人工急停激光锁存（X1-REQ-GMBL-0008 / X1-TC-GMBL-0008，P1，HIL/试飞占位）
    # ==================================================================

    @pytest.mark.p1
    @allure.severity(allure.severity_level.NORMAL)
    @allure.story("激光异常保护")
    @allure.title("P1 X1-TC-GMBL-0008 人工急停关闭激光锁存与解除恢复（AC-001~004，HIL/试飞占位）")
    def test_laser_estop_latch(self):
        """验证人工急停关闭锁存与解除恢复（AC-001~004）——真机台架
        不可达：前置要求剧本运行+激光输出（READY 态=解锁且 >20m）；
        且急停关闭/锁存解除的命令号未确认（40003 FLIGHT_STOP 是飞行
        急停，是否联动激光锁存待查——GCS-03 执行序"上锁=清急停"提示
        二者有关联但非同一命令）。待试飞/HIL 环境与急停命令口径确认
        后补全"""
        pytest.skip("前置需剧本运行+READY 激光输出态（解锁且 >20m，真机需"
                    "飞行）；急停关闭/锁存解除命令协议未确认（40003 为飞行"
                    "急停，激光锁存联动待查）——待试飞/HIL 环境与命令口径"
                    "确认后补全")

    # ==================================================================
    # 安装方向一致性（X1-REQ-GMBL-0009 / X1-TC-GMBL-0009，P1，HIL 占位）
    # ==================================================================

    @pytest.mark.p1
    @allure.severity(allure.severity_level.NORMAL)
    @allure.story("安装方向与上电检查")
    @allure.title("P1 X1-TC-GMBL-0009 云台安装方向上置/下置一致性检查与上电控制（AC-001~004，HIL 占位）")
    def test_gimbal_mount_direction_check(self):
        """验证剧本安装方向与物理通道方向一致性检查、结果上报与不一致
        禁止上电（AC-001~004）——剧本方向配置无地面注入手段、比较结果
        上报消息未知、端口供电监测需 HIL 工具，真机不可达；真机旁证=
        通道 3 与上视挂载组 1/3 一致（GMBL-0004 步骤 2 已旁证）。待
        HIL 台架/上报消息确认后补全"""
        pytest.skip("剧本安装方向配置（上置/下置）无真机注入手段，比较结果"
                    "上报消息未知，端口供电监测需 HIL 工具——待 HIL 台架或"
                    "上报消息确认后补全（真机旁证：通道 3 上视挂载一致，"
                    "见 test_gimbal_channel_match_flow 步骤 2）")

    # ==================================================================
    # 心跳掉线分级断电（X1-REQ-GMBL-0010 / X1-TC-GMBL-0010，P1，HIL 占位）
    # ==================================================================

    @pytest.mark.p1
    @allure.severity(allure.severity_level.NORMAL)
    @allure.story("心跳管理")
    @allure.title("P1 X1-TC-GMBL-0010 云台心跳掉线分级断电停控（AC-001~004，HIL 占位）")
    def test_gimbal_heartbeat_timeout(self):
        """验证云台心跳掉线两档超时保护（AC-001~004：激光侧 ≤1s 断电、
        飞控侧 2s 停发命令、恢复重新初始化）——停止云台心跳需 HIL 或
        物理断电云台；激光供电与飞控下发命令为内部信号不可观测；
        ≤1s/2s 时序需示波器/时标。真机不可达，待 HIL 台架补全
        （心跳→遥测链路见 GMBL-0041 gimbal_scaled，届时若 listener
        可用可升级真机观测）"""
        pytest.skip("停止云台心跳需 HIL 注入或物理断电；激光供电与飞控下发"
                    "命令为内部信号不可观测；≤1s/2s 时序需示波器/时标——"
                    "待 HIL 台架补全（gimbal_scaled 遥测若可读可升级真机"
                    "观测，见 GMBL-0041）")

    # ==================================================================
    # 云台热插拔重连（X1-REQ-GMBL-0011 / X1-TC-GMBL-0011，P1）
    # ==================================================================

    @pytest.mark.p1
    @allure.severity(allure.severity_level.NORMAL)
    @allure.story("热插拔与重连")
    @allure.title("P1 X1-TC-GMBL-0011 云台热插拔重连：拔出→重插→恢复受控（真机=单云台主场景）")
    def test_gimbal_hot_plug(self):
        """验证云台热插拔重连初始化（AC-001~003，单用例覆盖）。
        ⚠ 判据弱化声明（打开用例先看这里）：
        - 真机单云台可测主场景「运行中拔出→重插→恢复受控」；判据间接
          =重插后通道 3 指令恢复生效（行为探针，角度无遥测）
        - 供电/DAV 寻址/心跳/对象清理为内部监测 → 缺位；「上电前插入/
          上电后插入」两场景需整机断电重启（网络会话重建，脚本内不可
          达）→ 缺位；双云台互不影响（AC-003 后半）缺多云台
        - 拔插为人工物理操作：脚本以固定时间窗等待（附件醒目提示），
          运行时需操作者在场"""
        # 暂缓执行：需操作者在场完成拔/插物理操作，本轮批量跑批时不具备
        # （用例本体完整保留，恢复执行删掉本行 skip 即可）
        pytest.skip("热插拔需操作者在场完成拔出/重插物理操作，本轮跑批暂缓"
                    "（用例本体完整，待人工配合时恢复执行）")

        # ── 前置：受控基线 ────────────────────────────────────────────
        with allure.step("前置：gimbal 1 切 Debug，Lock(30°,0°) 受控基线"):
            resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
            assert 'set gimbal to debug mode' in resp.lower(), \
                f"未进入 Debug 模式: {resp[:200]}"
            ack = self._gimbal_lock_angle(30, 0, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, "基线指令被拒绝"
            log_manager.log_and_attach(
                "人工判读点：云台运动到 roll=30°（拔出前受控基线）", "人工观察")

        # ── 步骤 1：人工拔出（操作窗口）──────────────────────────────
        with allure.step("1. 人工拔出云台 CAN/负载线（10s 操作窗口）"):
            log_manager.log_and_attach(
                "▶ 请现在拔出云台 CAN/负载线（拔出后云台失去供电/通信），"
                "本步骤等待 10s", "人工操作提示")
            time.sleep(10.0)

        # ── 步骤 2：拔出态发指令 → 记录 ACK 行为 ────────────────────
        # 云台已离线，FC 对指令的回执行为未知（可能照回 result=0）——
        # expect_result=None 仅记录；云台无动作是必然（不在），不判据
        with allure.step("2. 拔出态发 Lock(40°,0°) → ACK 仅记录（云台已离线）"):
            ack = self._send_command_long(
                CMD_DO_SET_SERVO,
                param1=40, param2=0,
                param4=GIMBAL_CHANNEL, param7=11,
                expect_result=None)
            log_manager.log_and_attach(
                f"拔出态 ACK result={ack.fields.get('result')}"
                f"（仅记录：FC 对离线云台指令的回执行为）", "离线指令回执")

        # ── 步骤 3：人工重插（操作+重连初始化窗口）──────────────────
        with allure.step("3. 人工重新插入云台（15s 操作+重连初始化窗口）"):
            log_manager.log_and_attach(
                "▶ 请现在重新插入云台线——ADC 250ms 轮询识别 + 重新初始"
                "化，本步骤等待 15s", "人工操作提示")
            time.sleep(15.0)

        # ── 步骤 4：行为探针 → 恢复受控（重连间接判据）──────────────
        with allure.step("4. 重插后 Lock(40°,0°) → ACK=0，云台恢复受控（重连间接判据）"):
            ack = self._gimbal_lock_angle(40, 0, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, \
                f"重插后指令被拒绝（云台未恢复在线？）: {ack.fields}"
            log_manager.log_and_attach(
                "人工判读点：云台应运动到 roll=40°（恢复受控 = 重连与重新"
                "初始化成功的间接判据）", "人工观察")
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=2.0)

        # ── 步骤 5：缺位说明 ──────────────────────────────────────────
        with allure.step("5. 缺位说明：另两场景/内部初始化监测/双云台互不影响"):
            log_manager.log_and_attach(
                "缺位：①「上电前插入」「上电后插入」两场景需整机断电重启"
                "（网络会话重建，脚本内不可达）；②供电/DAV 寻址/心跳/对象"
                "清理（uninstall_can）为内部监测；③双云台互不影响需多云台"
                "挂载。待 HIL/多云台环境补全", "验证缺位")

    # ==================================================================
    # 激光帧 RGB 接收（X1-REQ-GMBL-0012 / X1-TC-GMBL-0012，P1）
    # ==================================================================

    @pytest.mark.p1
    @allure.severity(allure.severity_level.NORMAL)
    @allure.story("激光帧接收与输出")
    @allure.title("P1 X1-TC-GMBL-0012 激光帧 RGB 接收与 G/B 输出、R 抑制（相机判读·≤25 档）")
    def test_laser_rgb_receive(self):
        """验证 RGB 三字节接收、G/B 双路输出与 R 通道抑制（AC-001~003，
        单用例覆盖）。
        ⚠ 判据弱化声明（打开用例先看这里）：
        - 判据=相机光斑存在性（绿/蓝分检，_verify_spot）；亮灭无遥测
        - AC-003 重复帧重发输出（PWM 写入次数统计）需示波器/内部监听
          → 缺位
        - 数值口径：库值 (0,100,200) 超护眼限幅且会被 DISARMED 钳制
          （0005 实锤 Debug 模式不豁免钳制）→ 保守取 ≤25 原值档
          （g=20/b=13）；「>25 原值下发」待 CAN 抓包手段后补
        - R 抑制：X1 无红光硬件（param1=r 恒 0 的负载约定），直接发
          param1=255 预期无任何输出（负向判据）"""
        # ── 前置：相机 + Debug + 起始暗态 ──────────────────────────────
        with allure.step("前置：相机（按名 FF-Camera），gimbal 1 切 Debug，关光起始"):
            camera = None
            try:
                camera = LaserSpotCamera(camera_name="FF-Camera",
                                         width=1920, height=1080,
                                         exposure=-9).open()
            except Exception as e:
                log_manager.logger.warning(f"相机打开失败，光斑判读降级人工: {e}")
            resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
            assert 'set gimbal to debug mode' in resp.lower(), \
                f"未进入 Debug 模式: {resp[:200]}"
            self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)

        try:
            # ── 步骤 1：绿路单发 → 亮 ──────────────────────────────────
            with allure.step("1. 绿路 g=20 → ACK=0，相机验绿光斑亮"):
                ack = self._laser_color(20, 0, channel=LASER_BROADCAST_CHANNEL)
                assert ack.fields.get('result', -1) == 0, "绿路指令被拒绝"
                _verify_spot(camera, "green", True, "绿路 g=20")

            # ── 步骤 2：绿关 → 灭 ──────────────────────────────────────
            with allure.step("2. 关光 (0,0) → 相机验熄灭"):
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)
                _verify_spot(camera, "green", False, "绿路关")

            # ── 步骤 3：蓝路单发 → 亮 ──────────────────────────────────
            with allure.step("3. 蓝路 b=20 → ACK=0，相机验蓝光斑亮"):
                ack = self._laser_color(0, 20, channel=LASER_BROADCAST_CHANNEL)
                assert ack.fields.get('result', -1) == 0, "蓝路指令被拒绝"
                _verify_spot(camera, "blue", True, "蓝路 b=20")

            # ── 步骤 4：蓝关 → 灭 ──────────────────────────────────────
            with allure.step("4. 关光 (0,0) → 相机验熄灭"):
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)
                _verify_spot(camera, "blue", False, "蓝路关")

            # ── 步骤 5：G/B 双路同发 → 双色光斑 ────────────────────────
            # 库用例 RGB=(0,100,200) 双路同发的保守版
            with allure.step("5. 双路 (g=20, b=13) → ACK=0，相机验绿蓝双光斑"):
                ack = self._laser_color(20, 13, channel=LASER_BROADCAST_CHANNEL)
                assert ack.fields.get('result', -1) == 0, "双路指令被拒绝"
                _verify_spot(camera, "green", True, "双路·绿")
                _verify_spot(camera, "blue", True, "双路·蓝")
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)

            # ── 步骤 6：R 抑制 → 无任何输出 ────────────────────────────
            # 直接发 param1=255（绕过 _laser_color 的 r 恒 0 约定）——
            # X1 无红光硬件，预期绿/蓝均无输出；FC 回执行为未知不判据
            with allure.step("6. 仅 R 分量 (255,0,0) → 相机验无任何光斑（R 抑制）"):
                ack = self._send_command_long(
                    CMD_DO_SET_SERVO,
                    param1=255, param2=0, param3=0,   # 仅 R 分量
                    param4=LASER_BROADCAST_CHANNEL, param7=4,
                    expect_result=None)
                log_manager.log_and_attach(
                    f"仅 R 指令 ACK result={ack.fields.get('result')}"
                    f"（不判据）；判据=相机无任何光斑", "R 抑制响应")
                _verify_spot(camera, "green", False, "R 抑制",
                             fail_hint="——仅 R 分量不应有任何激光输出"
                                       "（R 恒 0 不参与输出）")

            # ── 步骤 7：缺位说明（AC-003 重复帧重发统计）───────────────
            with allure.step("7. 缺位说明：AC-003 重复帧重发输出统计"):
                log_manager.log_and_attach(
                    "AC-003（相同数值重复到达时重新执行 PWM 输出、写入次数"
                    "统计）需示波器/PWM 内部监听——真机不可验，判据缺位；"
                    ">25 原值下发受 DISARMED 钳制限制（0005 实锤），待 CAN "
                    "抓包手段后补", "验证缺位")
        finally:
            with allure.step("恢复：关激光 → 关相机"):
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)
                if camera is not None:
                    camera.close()

    # ==================================================================
    # 工作状态激光权限矩阵（X1-REQ-GMBL-0016 / X1-TC-GMBL-0016，P1）
    # ==================================================================

    @pytest.mark.p1
    @allure.severity(allure.severity_level.NORMAL)
    @allure.story("激光输出权限")
    @allure.title("P1 X1-TC-GMBL-0016 云台工作状态激光输出权限矩阵（真机=INIT/LD_PROT 禁 + DEBUG 允）")
    def test_laser_state_permission_matrix(self):
        """验证五态激光输出权限（GMBL-0016 矩阵：INIT/READY/DEBUG/
        LD_PROT/CALIB，AC-001~003，单用例覆盖）。
        ⚠ 判据弱化声明（打开用例先看这里）：
        - 真机可测 3/5 态：INIT 禁止 / LD_PROT 禁止 / DEBUG 允许（正向
          对照）；判据=相机光斑存在性（无遥测）
        - READY 允许（需解锁+真高 >20m，自动状态机 CLI 切不进）缺位
          待试飞；CALIB 禁止已移交 0029/38 校准族用例承载（校准中验
          不亮，探测口径·危险门控，见 test_gimbal_calibration_flow）
        - INIT/LD_PROT 态下发激光 ACK 可能照回 result=0（拒绝发生在
          下游权限层）→ expect_result=None 仅记录，判据纯看相机"""
        # ── 前置：相机；云台假设处于 Init（上电默认/前序 teardown 归位，
        # 无查询命令——attach 说明，若上条用例刚跑完 teardown 即为 Init）
        with allure.step("前置：相机（按名 FF-Camera），确认云台处于 Init（默认态）"):
            camera = None
            try:
                camera = LaserSpotCamera(camera_name="FF-Camera",
                                         width=1920, height=1080,
                                         exposure=-9).open()
            except Exception as e:
                log_manager.logger.warning(f"相机打开失败，光斑判读降级人工: {e}")
            log_manager.log_and_attach(
                "云台按 Init 态对待（上电默认/前序用例 teardown 归位；"
                "无模式查询命令，若不确定请先重启或跑完其他用例）", "前置说明")

        try:
            # ── 步骤 1：INIT 态发激光 → 禁止（相机验不亮）──────────────
            # 矩阵：INIT=初始化/收纳态，禁止激光输出
            with allure.step("1. INIT 态发 g=13 → 相机验不亮（INIT 禁止）"):
                ack = self._send_command_long(
                    CMD_DO_SET_SERVO,
                    param2=13, param3=0,
                    param4=LASER_BROADCAST_CHANNEL, param7=4,
                    expect_result=None)
                log_manager.log_and_attach(
                    f"INIT 态 ACK result={ack.fields.get('result')}"
                    f"（不判据）", "INIT 态回执")
                _verify_spot(camera, "green", False, "INIT 态",
                             fail_hint="——INIT 态禁止激光输出（GMBL-0016"
                                       " 矩阵），出现光斑即权限失效")

            # ── 步骤 2：DEBUG 态发激光 → 允许（正向对照）───────────────
            with allure.step("2. gimbal 1 切 Debug → 发 g=13 → 相机验亮（DEBUG 允许）"):
                resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
                assert 'set gimbal to debug mode' in resp.lower(), \
                    f"未进入 Debug 模式: {resp[:200]}"
                ack = self._laser_color(13, 0, channel=LASER_BROADCAST_CHANNEL)
                assert ack.fields.get('result', -1) == 0, "DEBUG 态指令被拒绝"
                _verify_spot(camera, "green", True, "DEBUG 态")
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)

            # ── 步骤 3：LD_PROT 态发激光 → 禁止 ────────────────────────
            # 切 LD_PROT 自身触发收纳（09-17 实锤），等静止后再发
            with allure.step("3. gimbal 2 切 LD_PROT（等收纳静止）→ 发 g=13 → 相机验不亮"):
                resp = self._gimbal_mode(GIMBAL_MODE_LD_PROT)
                assert 'set gimbal to ld protection mode' in resp.lower(), \
                    f"未进入 LD Protection 模式: {resp[:200]}"
                time.sleep(3.0)   # 收纳动作静止
                ack = self._send_command_long(
                    CMD_DO_SET_SERVO,
                    param2=13, param3=0,
                    param4=LASER_BROADCAST_CHANNEL, param7=4,
                    expect_result=None)
                log_manager.log_and_attach(
                    f"LD_PROT 态 ACK result={ack.fields.get('result')}"
                    f"（不判据）", "LD_PROT 态回执")
                _verify_spot(camera, "green", False, "LD_PROT 态",
                             fail_hint="——LD_PROT（落地保护）禁止激光输出"
                                       "（GMBL-0016 矩阵）")

            # ── 步骤 4：缺位说明（READY；CALIB 已移交 0029/38）──────────
            with allure.step("4. 缺位说明：READY 允许待试飞 / CALIB 已移交校准族用例"):
                log_manager.log_and_attach(
                    "READY 允许输出：需解锁且真高 >20m（自动状态机，CLI 切不"
                    "进）——待试飞；CALIB 禁止输出：已由 0029/38 校准族用例"
                    "承载（校准中发激光验不亮，探测口径·危险门控，见 "
                    "test_gimbal_calibration_flow）", "验证缺位")
        finally:
            with allure.step("恢复：关激光 → 关相机（模式由 fixture 兜底回 Init）"):
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)
                if camera is not None:
                    camera.close()

    # ==================================================================
    # 舵机轴映射（X1-REQ-GMBL-0024 / X1-TC-GMBL-0024，P1）
    # ==================================================================

    @pytest.mark.p1
    @allure.severity(allure.severity_level.NORMAL)
    @allure.story("舵机轴映射")
    @allure.title("P1 X1-TC-GMBL-0024 舵机 Pitch/Roll 轴映射：单轴指令+人工判读（映射不互换）")
    def test_gimbal_servo_axis_mapping(self):
        """验证 Pitch/Roll 轴舵机映射（AC-001~003，单用例覆盖）：
        Pitch↔45kg 大舵机、Roll↔15kg 小舵机，映射不互换。
        ⚠ 判据弱化声明（打开用例先看这里）：
        - 判据=人工观察哪个轴动 + 方向（角度无遥测，两舵机体积差异
          明显可辨）；UART2/UART3 报文走向与舵机规格对应需串口抓取
          → 缺位（真机验的是行为层映射：指令轴↔运动轴一致）
        - Lock 指令 param1=roll、param2=pitch（GMBL-0003 口径）"""
        # ── 前置：Debug + 归零 ──────────────────────────────────────────
        with allure.step("前置：gimbal 1 切 Debug，Lock(0°,0°) 起始基准"):
            resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
            assert 'set gimbal to debug mode' in resp.lower(), \
                f"未进入 Debug 模式: {resp[:200]}"
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=2.0)

        # ── 步骤 1：Roll 单轴 +30° ─────────────────────────────────────
        with allure.step("1. 归零 → Lock(roll=+30°, pitch=0°) → 人工判读 Roll 轴动、Pitch 不动"):
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            ack = self._gimbal_lock_angle(30, 0, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, "Roll 指令被拒绝"
            log_manager.log_and_attach(
                "人工判读点：应仅 Roll 轴（15kg 小舵机，横滚）运动到 +30°，"
                "Pitch 轴不动——若 Pitch 动了即映射互换（AC-003 违例）",
                "人工观察")

        # ── 步骤 2：Pitch 单轴 +30° ────────────────────────────────────
        with allure.step("2. 归零 → Lock(roll=0°, pitch=+30°) → 人工判读 Pitch 轴动、Roll 不动"):
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            ack = self._gimbal_lock_angle(0, 30, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, "Pitch 指令被拒绝"
            log_manager.log_and_attach(
                "人工判读点：应仅 Pitch 轴（45kg 大舵机，俯仰）运动到 +30°，"
                "Roll 轴不动——若 Roll 动了即映射互换", "人工观察")

        # ── 步骤 3：反向复核（-30°）────────────────────────────────────
        with allure.step("3. 归零 → 反向复核 Lock(roll=-30°,0°) / Lock(0°,pitch=-30°)"):
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            ack = self._gimbal_lock_angle(-30, 0, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, "Roll 反向指令被拒绝"
            log_manager.log_and_attach(
                "人工判读点：Roll 轴反向到 -30°", "人工观察")
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            ack = self._gimbal_lock_angle(0, -30, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, "Pitch 反向指令被拒绝"
            log_manager.log_and_attach(
                "人工判读点：Pitch 轴反向到 -30°（方向与轴均不互换）", "人工观察")

        # ── 步骤 4：混合指令 → 两轴同时动 ──────────────────────────────
        with allure.step("4. 归零 → 混合 Lock(20°, -20°) → 两轴同时运动"):
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=1.0)
            ack = self._gimbal_lock_angle(20, -20, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, "混合指令被拒绝"
            log_manager.log_and_attach(
                "人工判读点：两轴应同时各自运动（Roll→+20°，Pitch→-20°，"
                "链路统一）", "人工观察")

        # ── 步骤 5：缺位说明（UART 走向/规格对应）─────────────────────
        with allure.step("5. 缺位说明：UART2/UART3 报文走向与舵机规格对应"):
            log_manager.log_and_attach(
                "AC-001/002 的串口层判据（Roll↔UART2↔15kg、Pitch↔UART3↔"
                "45kg 的报文走向）需串口抓取工具——真机不可验，缺位；本用例"
                "验证行为层映射（指令轴↔运动轴一致、不互换）。待串口/CAN "
                "工具补全", "验证缺位")

        # ── 恢复：归零 ──────────────────────────────────────────────────
        with allure.step("恢复：Lock(0°, 0°) 归零"):
            self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=2.0)

    # ==================================================================
    # 降落保护收纳/卸力策略（X1-REQ-GMBL-0026 / X1-TC-GMBL-0026，P0）
    # ==================================================================

    @pytest.mark.p0
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.story("降落保护策略")
    @allure.title("P0 X1-TC-GMBL-0026 降落保护收纳/卸力策略（真机=上置挂载双轴卸力验证）")
    def test_gimbal_landing_stow(self):
        """验证降落保护安装方向策略（AC-001~003，单用例覆盖）。
        ⚠ 判据弱化声明（打开用例先看这里）：
        - 真机为上置挂载（通道 3，conftest 口径）→ 可测 AC-002 上置
          策略=**双轴卸力、不移动至收纳角**；触发=切 LD Protection
          （0002 步骤 6 先例，落地保护链路）；判据=收纳动作人工观察 +
          手动转动两轴验证卸力（无遥测）
        - AC-001 下置策略（一轴收纳角+另一轴卸力）需下置挂载/换装 →
          缺位；AC-003 通道无效（HIL 注入）缺位
        - ★需求矛盾待判：09-17 实测切 LD_PROT 云台"走到收纳位"——若与
          「上置双轴卸力不移动」矛盾，可能是卸力后重力/结构自然下垂
          （视觉像主动移动），步骤 2 的手动验证即为定分晓环节"""
        # ── 前置：Debug + 两轴离开收纳位 ────────────────────────────────
        with allure.step("前置：gimbal 1 切 Debug，Lock(30°,-20°) 两轴离开收纳位"):
            resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
            assert 'set gimbal to debug mode' in resp.lower(), \
                f"未进入 Debug 模式: {resp[:200]}"
            self._gimbal_lock_angle(30, -20, channel=GIMBAL_CHANNEL, settle=2.0)
            log_manager.log_and_attach(
                "人工判读点：云台应在 (roll=30°, pitch=-20°)——两轴均离开"
                "收纳位，降落保护策略可观察", "人工观察")

        # ── 步骤 1：触发降落保护（切 LD_PROT）→ 观察云台行为 ──────────
        with allure.step("1. gimbal 2 触发降落保护（LD_PROT）→ 等静止，人工判读是否自主移至收纳位"):
            resp = self._gimbal_mode(GIMBAL_MODE_LD_PROT)
            assert 'set gimbal to ld protection mode' in resp.lower(), \
                f"未进入 LD Protection 模式: {resp[:200]}"
            time.sleep(3.0)   # 动作/自然下垂静止
            log_manager.log_and_attach(
                "人工判读点①：记录云台行为——是否**自主移动**至收纳位（上置"
                "策略预期不主动移动；若移动，区分主动走位与卸力后自然下垂："
                "听舵机动作声/观察是否分步到位）", "人工观察")

        # ── 步骤 2：手动验证卸力（上置=双轴卸力）──────────────────────
        with allure.step("2. 手动转动 Pitch/Roll 两轴验证卸力（上置预期双轴可自由转动）"):
            log_manager.log_and_attach(
                "人工判读点②：轻推 Pitch 与 Roll 两轴——可自由转动/跟随"
                "重力垂落 = 卸力（AC-002 上置策略成立）；锁死保持力矩 = "
                "保持锁力（与上置双轴卸力预期不符，若一轴锁死在收纳角更"
                "接近下置策略——记问题单核对安装方向配置）", "人工观察")

        # ── 步骤 3：重复触发稳定性（第二轮）───────────────────────────
        # 单向环：LD_PROT → Init → Debug 后再次触发
        with allure.step("3. 重复触发：gimbal 0 → 1 回 Debug，Lock(30°,-20°) → gimbal 2 再触发，策略一致"):
            resp = self._gimbal_mode(GIMBAL_MODE_INIT)
            assert 'set gimbal to init mode' in resp.lower(), \
                f"未回到 Init 模式: {resp[:200]}"
            time.sleep(1.0)
            resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
            assert 'set gimbal to debug mode' in resp.lower(), \
                f"未进入 Debug 模式: {resp[:200]}"
            self._gimbal_lock_angle(30, -20, channel=GIMBAL_CHANNEL, settle=2.0)
            resp = self._gimbal_mode(GIMBAL_MODE_LD_PROT)
            assert 'set gimbal to ld protection mode' in resp.lower(), \
                f"未进入 LD Protection 模式: {resp[:200]}"
            time.sleep(3.0)
            log_manager.log_and_attach(
                "人工判读点③：第二轮触发后策略与第一轮一致（AC-002 稳定性："
                "双轴卸力、行为可复现）", "人工观察")

        # ── 步骤 4：缺位说明（AC-001 下置 / AC-003 通道无效）───────────
        with allure.step("4. 缺位说明：下置策略与通道无效场景待换装/HIL"):
            log_manager.log_and_attach(
                "AC-001 下置策略（一轴收纳角+另一轴卸力）需下置挂载（通道"
                "2/4，物理换装）；AC-003 通道无效需 HIL 注入安装方向配置"
                "通道数据——均真机不可达，待换装/HIL 补全。★另：本用例"
                "步骤 1/2 的观察将裁决「切 LD_PROT 走收纳位」实测与需求"
                "「上置双轴卸力不移动」是否矛盾（卸力下垂 vs 主动走位）",
                "验证缺位")

        # 恢复：止于 LD_PROT，fixture 兜底 gimbal 0 回 Init

    # ==================================================================
    # 云台零点校准族（X1-REQ-GMBL-0029 + 0038 / X1-TC-GMBL-0029 + 0038，P1）
    # ==================================================================

    # 40040 param1=8（CALI_GIMBAL 云台校准类型，推定猜值）：0~6 见 mavlink
    # 枚举（file/mavlink_version/dmd_uav_42.py:536）、7=激光（LASER 校准
    # 真机实证）、8 无任何文档/源码出处——按序顺延推定，★待真机验证
    # （本用例即为该口径的探测实证：三项启动证据全弱 → 口径仍待固件组）
    CALI_TYPE_GIMBAL = 8

    @pytest.mark.p1
    @allure.severity(allure.severity_level.NORMAL)
    @allure.story("校准族")
    @allure.title("P1 X1-TC-GMBL-0029/0038 云台零点校准触发+校准中激光抑制"
                  "（探测口径·危险门控；0016 CALIB 分支在此落地）")
    @calib_probe_gate
    def test_gimbal_calibration_flow(self):
        """验证云台零点校准触发链路与校准期约束（GMBL-0038 AC-001~003 +
        GMBL-0029 AC-001/002/004，单用例覆盖）。
        ⚠ 判据弱化声明（打开用例先看这里）：
        - CALI_GIMBAL 的 40040 param1 取值（本用例推定 8）无文档实证
          ——整条为**探测口径**：校准启动证据 = TP_SENSOR_CALI 发布率
          上升（GCS-15 实锤通道）+ 人工判读（黄灯闪/舵机卸力），三项
          证据全弱 → p1=8 口径落空，如实记录待固件组确认（不硬判失败）
        - CALIB 态无遥测（云台心跳 calibrating 为 FC 内部信号）→ 校准
          中激光"验不亮"是强断言（校准期出光即 0029 AC-001 违例），
          但"确属 CALIB 抑制而非 INIT 抑制"依赖上述启动证据链区分
        - AC-003 逐轴内部流程（卸力→写原点→0° 回读复核）无观测手段 →
          缺位；AC-002"环节卡住"注入需 HIL，真机只验 30s 上限内自行
          结束；0038 AC-002 的 READY 态分支（真机 READY 不可达）以
          Debug 态代验"非 INIT 不触发"
        - ⚠ 危险：校准写原点落盘（跑后建议人工重校）+ 校准中舵机卸力
          （轴可能自然下垂）；运行时需操作者在场（黄灯/卸力判读）"""
        # 暂缓执行：零点校准写原点落盘（跑后需人工重校）+ p1=8 推定口径
        # 待固件组确认，本轮跑批暂缓（用例本体完整保留，恢复执行删掉
        # 本行 skip 即可）
        pytest.skip("云台校准族本轮暂缓：零点校准写原点落盘（跑后建议人工"
                    "重校）且 p1=8 为推定猜值待固件组确认（用例本体完整，"
                    "恢复执行删掉本行 skip 即可）")
        # 发布率提取（GCS-15 _cali_pub_rate 同款口径；固件 dt 打印器缺陷
        # 字段值打不出，仅率行可用——"TP_SENSOR_CALI(x.xx pub/s)"）
        def _pub_rate(dt_text):
            m = re.search(r'TP_SENSOR_CALI\(([\d.]+) pub/s\)', dt_text or '')
            return float(m.group(1)) if m else None

        rate_trend = []   # (标签, 发布率)——校准生效与否的行为证据链

        def _sample_rate(label):
            text = self._send_console_cmd("dt TP_SENSOR_CALI")
            rate = _pub_rate(text)
            rate_trend.append((label, rate))
            return rate

        # ── 前置：相机 + Debug 激光正向基线 ──────────────────────────
        camera = None
        try:
            with allure.step("前置：相机 + gimbal 1 Debug + g=13 验亮（激光链路基线）"):
                try:
                    camera = LaserSpotCamera(camera_name="FF-Camera",
                                             width=1920, height=1080,
                                             exposure=-9).open()
                except Exception as e:
                    log_manager.logger.warning(f"相机打开失败，光斑判读降级人工: {e}")
                resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
                assert 'set gimbal to debug mode' in resp.lower(), \
                    f"未进入 Debug 模式: {resp[:200]}"
                ack = self._laser_color(13, 0, channel=LASER_BROADCAST_CHANNEL)
                assert ack.fields.get('result', -1) == 0, "基线激光指令被拒绝"
                _verify_spot(camera, "green", True, "前置基线")
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)

            # ── 步骤 1：Debug 态（非 INIT）触发 → 不触发（AC-002）────
            # 需求：仅 Init 态转发 CALIBRATE_GIMBAL(34)。行为探针 = 触发
            # 后 Debug 激光仍可控（校准若抢占状态机，Debug 允许会失效）
            with allure.step("1. Debug 态触发校准 (40040, p1=8, p2=1) → 激光仍可控（非 INIT 不触发）"):
                ack = self._send_command_long(
                    CMD_CALIB_SENSOR, param1=self.CALI_TYPE_GIMBAL, param2=1,
                    expect_result=None)   # 猜值探测：result 仅记录不判据
                log_manager.log_and_attach(
                    f"Debug 态触发 ACK result={ack.fields.get('result')}"
                    f"（仅记录：拒绝可能发生在转发层，回执不可判）",
                    "非 INIT 触发回执")
                _sample_rate("Debug 态触发后")
                ack = self._laser_color(13, 0, channel=LASER_BROADCAST_CHANNEL)
                assert ack.fields.get('result', -1) == 0, "探针激光指令被拒绝"
                _verify_spot(camera, "green", True, "Debug 态探针",
                             fail_hint="——非 INIT 触发后 Debug 激光失效，"
                                       "疑似校准被意外触发/状态机被抢占"
                                       "（0038 AC-002 违例）")
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)

            # ── 步骤 2：回 Init（校准前置：仅 INIT 允许）───────────────
            with allure.step("2. 回 Init（Debug→LD_PROT→Init 单向链，校准前置态）"):
                self._gimbal_restore_init()
                time.sleep(3.0)   # 途经 LD_PROT 的收纳/卸力动作静止
                _sample_rate("Init 基线")

            # ── 步骤 3：Init 触发校准 → 启动证据采样 ────────────────────
            with allure.step("3. Init 触发校准 (40040, p1=8, p2=1) → 人工判读窗（黄灯/卸力）"):
                log_manager.log_and_attach(
                    "▶ 人工判读窗 8s：①飞控指示灯是否闪黄灯（0029 AC-004）；"
                    "②轻推 Pitch/Roll 两轴是否卸力（逐轴卸力=校准真跑的"
                    "行为证据，校准总超时 30s 内有效）；③舵机是否有动作声",
                    "人工操作提示")
                ack = self._send_command_long(
                    CMD_CALIB_SENSOR, param1=self.CALI_TYPE_GIMBAL, param2=1,
                    expect_result=None)   # 猜值探测：result 仅记录不判据
                log_manager.log_and_attach(
                    f"Init 态触发 ACK result={ack.fields.get('result')}"
                    f"（仅记录：p1=8 猜值，result=4 也可能=口径落空）",
                    "校准触发回执")
                time.sleep(8.0)   # 人工判读窗（校准 30s 超时内）
                _sample_rate("校准中")

            # ── 步骤 4：校准中发激光 → 验不亮（CALIB 分支判据）────────
            # 强断言：无论 CALIB 抑制还是 INIT 抑制，校准期出光都是
            # 0029 AC-001 违例；归属区分交给步骤 3 启动证据链
            with allure.step("4. 校准中发 g=13 → 相机验不亮（校准期禁出光，0016 CALIB 分支）"):
                ack = self._send_command_long(
                    CMD_DO_SET_SERVO,
                    param2=13, param3=0,
                    param4=LASER_BROADCAST_CHANNEL, param7=4,
                    expect_result=None)
                log_manager.log_and_attach(
                    f"校准中激光 ACK result={ack.fields.get('result')}"
                    f"（不判据）；判据=相机无光斑", "校准中激光回执")
                _verify_spot(camera, "green", False, "校准中",
                             fail_hint="——校准期间激光出光即 0029 AC-001"
                                       "违例（CALIB/INIT 抑制均不应放行）")

            # ── 步骤 5：30s 总超时窗 → 自行结束 ─────────────────────────
            with allure.step("5. 等 35s 超时窗（30s 上限+余量）→ 率回落 + 黄灯停（AC-002/AC-003 回落）"):
                time.sleep(35.0)
                _sample_rate("超时窗后")
                log_manager.log_and_attach(
                    "人工判读点：校准应已自行结束（≤30s 总超时）——飞控"
                    "黄灯应停止闪烁；若黄灯仍在闪=校准超时未中止（0029 "
                    "AC-002 违例，记问题单）", "人工观察")

            # ── 步骤 6：回落验证（权限恢复）→ 停止兜底 ─────────────────
            with allure.step("6. 切 Debug → g=13 验亮（权限恢复=校准退出未卡死）"):
                resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
                assert 'set gimbal to debug mode' in resp.lower(), \
                    f"校准后切 Debug 失败（状态卡死?）: {resp[:200]}"
                ack = self._laser_color(13, 0, channel=LASER_BROADCAST_CHANNEL)
                assert ack.fields.get('result', -1) == 0, "恢复探针激光指令被拒绝"
                _verify_spot(camera, "green", True, "校准后恢复",
                             fail_hint="——校准结束后 Debug 激光不亮，疑似"
                                       "状态未回落 INIT/权限未恢复（0038 "
                                       "AC-003 违例）")
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)

            # ── 步骤 7：停止兜底 + 趋势汇总 + 缺位说明 ──────────────────
            with allure.step("7. 停止兜底 (p1=0, p2=2) + 发布率趋势汇总 + 缺位说明"):
                self._send_command_long(
                    CMD_CALIB_SENSOR, param1=0, param2=2,   # 停止（GCS-15 口径）
                    expect_result=None)   # 校准已自然结束时 result 仅记录
                if rate_trend:
                    log_manager.log_and_attach(
                        "TP_SENSOR_CALI 发布率趋势（校准中上升=校准真实"
                        "生效，ACK 假成功之外的铁证；三项启动证据（率/"
                        "黄灯/卸力）全弱 → p1=8 口径落空待固件组）:\n"
                        + '\n'.join(f"  {label}: {rate} pub/s"
                                    for label, rate in rate_trend),
                        "校准发布率趋势")
                log_manager.log_and_attach(
                    "缺位：①AC-003 逐轴内部流程（卸力→写原点→0° 回读"
                    "复核）为云台内部无观测手段；②AC-002 环节卡住注入需"
                    " HIL（真机只验 30s 上限内自行结束）；③0038 AC-002 的"
                    " READY 态拒绝分支需试飞环境（Debug 态已代验非 INIT "
                    "不触发）；④若步骤 3 启动证据全弱，p1=8 猜值落空，"
                    "全链路口径待固件组确认。⚠ 零点已写过（若校准真实"
                    "生效），建议人工重校后再跑角度类用例", "验证缺位")
        finally:
            with allure.step("恢复：关激光 → 停止校准兜底 → 关相机（模式由 fixture 兜底回 Init）"):
                try:
                    self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)
                    self._send_command_long(
                        CMD_CALIB_SENSOR, param1=0, param2=2,
                        expect_result=None, quiet=True)   # 不留后台校准
                except Exception as e:
                    log_manager.logger.warning(f"恢复段兜底命令发送失败: {e}")
                if camera is not None:
                    camera.close()
