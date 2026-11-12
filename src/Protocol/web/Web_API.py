from datetime import datetime

from src.Physical.WebBase.APIBase import APIBase, root_path
from functools import wraps

curr_date = datetime.today().strftime('%Y-%m-%d')


class WEBCloud(APIBase):
    def __init__(self):
        super().__init__()
        self.read_excel("webCloud")

    @staticmethod
    def prepare_request(case_name):
        def decorator(func):
            @wraps(func)
            def wrapper(self, *args, **kwargs):
                dynamic_args = kwargs.pop("dynamic_args", None)
                jsonpath_args = kwargs.pop("jsonpath_args", None)
                assertions = kwargs.pop("assertions", None)
                files = kwargs.pop("files", None)

                data_set = self._get_params(case_name)
                request_config = self.build_request(data_set, dynamic_args, jsonpath_args)
                if files:
                    request_config["files"] = files

                response = self.request(**request_config)

                if assertions:
                    self.assert_response(
                        response,
                        assertions
                    )

                return func(self, response, *args, **kwargs)

            return wrapper

        return decorator

    # =========================
    # 业务接口定义
    # =========================
    @prepare_request("get_token")
    def get_token(self, response):
        data = response.get("data")
        if not data:
            return response

        token = data.get("token")
        if token:
            self.session.cookies.update({
                "Authorization": token
            })

        return response

    # =========================
    # 无人机设备接口
    # =========================
    @prepare_request("edit_device")
    def edit_device(self, response):
        """编辑设备接口，可以修改仓库组织，设备状态等"""
        return response

    @prepare_request("search_device")
    def search_device(self, response):
        """查询设备接口"""
        return response

    # =========================
    # 飞行项目接口
    # =========================
    @prepare_request("add_project")
    def add_project(self, response):
        """新增飞行项目"""
        return response

    @prepare_request("search_project")
    def search_project(self, response):
        """查询飞行项目"""
        return response

    @prepare_request("edit_project")
    def edit_project(self, response):
        """编辑飞行项目"""
        return response

    @prepare_request("add_self_order")
    def add_self_order(self, response):
        """新增自用订单"""
        return response

    @prepare_request("search_self_order")
    def search_self_order(self, response):
        """查询项目自用订单"""
        return response

    @prepare_request("self_order_outbound")
    def self_order_outbound(self, response):
        """自用订单出库"""
        return response

    @prepare_request("self_order_inbound")
    def self_order_inbound(self, response):
        """自用订单归还入库"""
        return response

    @prepare_request("search_rent_source")
    def search_rent_source(self, response):
        """查询租借资源"""
        return response

    @prepare_request("add_rent_source")
    def add_rent_source(self, response):
        """上架租借设备资源"""
        return response

    @prepare_request("add_rent_order")
    def add_rent_order(self, response):
        """添加租借订单"""
        return response

    @prepare_request("search_rent_order")
    def search_rent_order(self, response):
        """根据项目id查询租借订单"""
        return response

    @prepare_request("detail_rent_order")
    def detail_rent_order(self, response):
        """租借订单详情"""
        return response

    @prepare_request("confirm_rent_order")
    def confirm_rent_order(self, response):
        """确认租借订单"""
        return response

    @prepare_request("rent_out_outbound")
    def rent_out_outbound(self, response):
        """借出方出库"""
        return response

    @prepare_request("rent_in_inbound")
    def rent_in_inbound(self, response):
        """借入方入库"""
        return response

    @prepare_request("rent_in_outbound")
    def rent_in_outbound(self, response):
        """借入方出库"""
        return response

    @prepare_request("rent_out_inbound")
    def rent_out_inbound(self, response):
        """借出方入库"""
        return response

    @prepare_request("gdbc_device_inbound")
    def gdbc_device_inbound(self, response):
        """地面站入库设备"""
        return response

    @prepare_request("bind_list")
    def bind_list(self, response):
        """入库待绑定设备信息"""
        return response

    @prepare_request("bind_device")
    def bind_device(self, response):
        """设备绑定rfid"""
        return response

    @prepare_request("delete_device")
    def delete_device(self, response):
        """根据设备id删除设备"""
        return response

    @prepare_request("flight_project_dashboard")
    def flight_project_dashboard(self, response):
        """飞行项目看板
        """
        return response

    @prepare_request("equipment_out_item")
    def equipment_out_item(self, response):
        """项目设备调出
        """
        return response

    # =========================
    # 无人机设备接口
    # =========================
    @prepare_request("device_count_status")
    def device_count_status(self, response):
        """设备状态统计
        """
        return response

    @prepare_request("device_usage_rate")
    def device_usage_rate(self, response):
        """设备使用率统计
        """
        return response

    @prepare_request("device_count_type")
    def device_count_type(self, response):
        """设备类型统计
        """
        return response

    # =========================
    # 地面站接口
    # =========================
    @prepare_request("edit_dgcs_user")
    def edit_dgcs_user(self, response):
        """编辑授权用户信息，授权功能，激活次数，设备类型，飞机数量授权到期时间等"""
        return response

    @prepare_request("dgcs_search")
    def dgcs_search(self, response):
        """地面站搜索，可获取地面站id，类型值"""
        return response

    @prepare_request("dgcs_user_list")
    def dgcs_user_list(self, response):
        """根据地面站id查询授权用户，可以传入用户名单独查询"""
        return response

    @prepare_request("adjacent_project_list")
    def adjacent_project_list(self, response):
        """根据经纬度查询周边四公里内的临近飞行项目"""
        return response

    @prepare_request("dgcs_func_list")
    def dgcs_func_list(self, response):
        """根据地面站id查询授权功能信息"""
        return response

    @prepare_request("in_out_record")
    def in_out_record(self, response):
        """出入库记录，可根据仓库编码，出库单号过滤查询"""
        return response

    @prepare_request("calculate_price")
    def calculate_price(self, response):
        """根据设备类型，数量，租借天数结合费用配置计算价格，没有配置价格的设备会计算失败"""
        return response

    @prepare_request("dgcs_add_user")
    def dgcs_add_user(self, response):
        """地面站添加用户，需要传入对应地面站id与用户名，其他功能，机型，参数以id形式传递，
        激活次数，到期时间，最大飞机数量等参数
        """
        return response

    @prepare_request("activation_records")
    def activation_records(self, response):
        """地面站用户激活，根据当前登录用的token，传入机器码，地面站类型值
        """
        return response

    @prepare_request("user_details")
    def user_details(self, response):
        """根据机器码获取用户详细信息，是否允许登录等
        """
        return response

    @prepare_request("project_list")
    def project_list(self, response):
        """地面站获取飞行项目
        """
        return response

    @prepare_request("send_repair")
    def send_repair(self, response):
        """手持送修设备
        """
        return response

    @prepare_request("cancel_order")
    def cancel_order(self, response):
        """取消维修订单
        """
        return response

    @prepare_request("dgcs_del_user")
    def dgcs_del_user(self, response):
        """地面站删除授权用户
        """
        return response

    @prepare_request("add_dgcs")
    def add_dgcs(self, response):
        """新增地面站软件
        """
        return response

    @prepare_request("delete_dgcs")
    def delete_dgcs(self, response):
        """删除地面站软件
        """
        return response

    # =========================
    # 素材中心接口
    # =========================
    @prepare_request("material_group_list")
    def material_group_list(self, response):
        """素材组列表接口
        """
        return response

    # =========================
    # 库存管理接口
    # =========================
    @prepare_request("inventory_task_add")
    def inventory_task_add(self, response):
        """新增库存盘点任务
        """
        return response

    @prepare_request("warehouse_list")
    def warehouse_list(self, response):
        """仓库列表
        """
        return response

    @prepare_request("inventory_task_list")
    def inventory_task_list(self, response):
        """盘点任务列表
        """
        return response

    @prepare_request("start_check")
    def start_inventory_task(self, response):
        """开始盘点任务
        """
        return response

    @prepare_request("commit_devices_data")
    def commit_devices_data(self, response):
        """提交盘点数据
        """
        return response

    @prepare_request("finish_task")
    def finish_inventory_task(self, response):
        """完成盘点
        """
        return response

    @prepare_request("query_record_list")
    def query_record_list(self, response):
        """盘点记录清单
        """
        return response

    @prepare_request("get_inventory_adjustment")
    def get_inventory_adjustment(self, response):
        """获取库存调整
        """
        return response

    @prepare_request("create_inventory_adjustment")
    def create_inventory_adjustment(self, response):
        """创建库存调整
        """
        return response

    # =========================
    # 评级管理
    # =========================
    @prepare_request("rating_type_list")
    def rating_type_list(self, response):
        """获取等级类型（设计师，动画师，建模师，飞手）
        """
        return response

    @prepare_request("rating_icon_list")
    def rating_icon_list(self, response):
        """获取等级图标连接url
        """
        return response

    @prepare_request("add_rating_level")
    def add_rating_level(self, response):
        """新增等级名称
        """
        return response

    @prepare_request("rating_level_list")
    def rating_level_list(self, response):
        """评级等级列表
        """
        return response

    @prepare_request("add_rating_user")
    def add_rating_user(self, response):
        """添加评级用户
        """
        return response

    @prepare_request("add_flyer_cost")
    def add_flyer_cost(self, response):
        """添加飞手费用配置
        """
        return response

    @prepare_request("rating_user_list")
    def rating_user_list(self, response):
        """评级用户列表
        """
        return response

    @prepare_request("change_rent_flag")
    def change_rent_flag(self, response):
        """飞手加入租借
        """
        return response

    @prepare_request("user_resource_list")
    def user_resource_list(self, response):
        """飞手资源列表
        """
        return response

    @prepare_request("calculate_flyer_cost")
    def calculate_flyer_cost(self, response):
        """计算飞手服务价格
        """
        return response

    @prepare_request("create_flyer_order")
    def create_flyer_order(self, response):
        """创建飞手租借订单
        """
        return response

    @prepare_request("flyer_order_list")
    def flyer_order_list(self, response):
        """飞手订单列表
        """
        return response

    @prepare_request("confirm_flyer_order")
    def confirm_flyer_order(self, response):
        """确认飞手订单
        """
        return response

    @prepare_request("update_flyer_order")
    def update_flyer_order(self, response):
        """更新飞手租赁订单状态
        """
        return response

    @prepare_request("flyr_cost_list")
    def flyr_cost_list(self, response):
        """飞手一般费用配置列表
        """
        return response

    @prepare_request("delete_flyer_cost")
    def delete_flyer_cost(self, response):
        """删除飞手费用配置
        """
        return response

    @prepare_request("delete_rating_user")
    def delete_rating_user(self, response):
        """删除评级用户
        """
        return response

    @prepare_request("delete_rating_level")
    def delete_rating_level(self, response):
        """删除评级等级
        """
        return response

    @prepare_request("update_repair_site")
    def update_repair_site(self, response):
        """确认维修订单
        """
        return response

    @prepare_request("update_repair_status")
    def update_repair_status(self, response):
        """维修订单状态流转
        """
        return response

    @prepare_request("upload_darma_jsdm")
    def upload_darma_jsdm(self, response):
        """素材中心上传jsdm文件
        """
        return response

    @prepare_request("add_drama_material")
    def add_drama_material(self, response):
        """素材中心添加素材
        """
        return response

    @prepare_request("delete_drama_material")
    def delete_drama_material(self, response):
        """素材中心删除素材
        """
        return response

    @prepare_request("list_drama_material")
    def list_drama_material(self, response):
        """素材中心添加素材
        """
        return response

    @prepare_request("change_material_status")
    def change_material_status(self, response):
        """素材下架
        """
        return response

    @prepare_request("sys_user_list")
    def sys_user_list(self, response):
        """系统用户列表
        """
        return response

    @prepare_request("sys_user_edit")
    def sys_user_edit(self, response):
        """系统用户编辑
        """
        return response

    @prepare_request("add_dispatch_order")
    def add_dispatch_order(self, response):
        """新增设备调度订单
        """
        return response

    @prepare_request("list_dispatch_order")
    def list_dispatch_order(self, response):
        """手持设备获取调度单
        """
        return response

    @prepare_request("outbound_dispatch_devices")
    def outbound_dispatch_devices(self, response):
        """调度单出库
        """
        return response

    @prepare_request("return_dispatch_devices")
    def return_dispatch_devices(self, response):
        """调度单出库
        """
        return response

    @prepare_request("sys_depart_list")
    def sys_depart_list(self, response):
        """系统部门列表
        """
        return response