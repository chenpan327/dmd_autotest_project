import json
import sys

from matplotlib.pyplot import scatter
import numpy as np

from utils.logger import logger

# 修复 Windows 控制台 UTF-8 输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ERROR_CODE = {
    0: "成功",
    1: "未知错误",
    2: "文件不存在",
    3: "文件格式错误",
    4: "数据差异较大",
    5: "数据不一致",
    # 可以根据需要添加更多错误代码和描述
}

class DrmCompare:
    def __init__(self, drama_json=None, dat_json=None, drama_data=None, dat_data=None):
        if drama_data is not None:
            self.drama_data = drama_data
        elif drama_json is not None:
            with open(drama_json, 'r', encoding='utf-8') as f:
                self.drama_data = json.load(f)
        else:
            logger.error("必须提供 drama_json 文件路径或 drama_data 数据")
            raise ValueError("必须提供 drama_json 文件路径或 drama_data 数据")

        if dat_data is not None:
            self.dat_data = dat_data
        elif dat_json is not None:
            with open(dat_json, 'r', encoding='utf-8') as f:
                self.dat_data = json.load(f)
        else:
            logger.error("必须提供 dat_json 文件路径或 dat_data 数据")
            raise ValueError("必须提供 dat_json 文件路径或 dat_data 数据")

        self.points_length = 0
        self.xs1, self.ys1, self.zs1 = [], [], []
        self.xs2, self.ys2, self.zs2 = [], [], []
        self.colors1 = []
        self.colors2 = []

        self.possition_difference_threshold = 1.732e-1  # 可以根据需要调整阈值
        self.light_difference_threshold = 1e-5  # 可以根据需要调整阈值
        self.point_differecne_list = []
        self.light_differecne_list = []

    def compare_one_drone_data(self):
        
        if self.drama_data["pointFps"] != self.dat_data["pointFps"]:
            logger.error(f"pointFps 不同：drama_json={self.drama_data['pointFps']} vs dat_json={self.dat_data['pointFps']}")
            return 5  # 返回错误代码 5：数据不一致
        if self.drama_data["payloadFps"] != self.dat_data["payloadFps"]:
            logger.error(f"payloadFps 不同：drama_json={self.drama_data['payloadFps']} vs dat_json={self.dat_data['payloadFps']}")
            return 5  # 返回错误代码 5：数据不一致
        if self.drama_data["totalPointFrameCount"] != self.dat_data["totalPointFrameCount"]:
            logger.error(f"totalPointFrameCount 不同：drama_json={self.drama_data['totalPointFrameCount']} vs dat_json={self.dat_data['totalPointFrameCount']}")
            return 5  # 返回错误代码 5：数据不一致
        if self.drama_data["totalPayloadFrameCount"] != self.dat_data["totalPayloadFrameCount"]:
            logger.error(f"totalPayloadFrameCount 不同：drama_json={self.drama_data['totalPayloadFrameCount']} vs dat_json={self.dat_data['totalPayloadFrameCount']}")
            return 5  # 返回错误代码 5：数据不一致
        
        self.points_length = max(self.drama_data["totalPointFrameCount"], self.drama_data["totalPayloadFrameCount"])
        logger.info(f"总帧数：{self.points_length}")
        for frame_id in range(self.points_length):
            point_positions1 = None
            point_light1 = None
            point_positions2 = None
            point_light2 = None

            temp_drama_data = self.drama_data[str(frame_id)]
            temp_dat_data = self.dat_data[str(frame_id)]

            for data in temp_drama_data:
                if "x" in data and "y"  in data and "z" in data:
                    point_positions1 = data
                    self.xs1.append(data["x"])
                    self.ys1.append(data["y"])
                    self.zs1.append(data["z"])

                if "r" in data and "g" in data and "b" in data:
                    point_light1 = data
                    self.colors1.append((data["r"] / 255.0, data["g"] / 255.0, data["b"] / 255.0))


            for data in temp_dat_data:
                if "x" in data and "y"  in data and "z" in data:
                    point_positions2 = data
                    self.xs2.append(data["x"])
                    self.ys2.append(data["y"])
                    self.zs2.append(data["z"])

                if "r" in data and "g" in data and "b" in data:
                    point_light2 = data
                    self.colors2.append((data["r"] / 255.0, data["g"] / 255.0, data["b"] / 255.0))

            if point_positions1 is None or point_positions2 is None:
                logger.error(f"第 {frame_id} 帧缺少位置信息")
                return 5  # 返回错误代码 5：数据不一致
            else:
                point_difference = (
                    (point_positions1["x"] - point_positions2["x"]) ** 2 +
                    (point_positions1["y"] - point_positions2["y"]) ** 2 +
                    (point_positions1["z"] - point_positions2["z"]) ** 2
                    ) ** 0.5
                
                self.point_differecne_list.append(point_difference)
                if point_difference > self.possition_difference_threshold:  # 可以根据需要调整阈
                    # print(f"第 {frame_id} 帧位置信息不同，差异为 {point_difference}")
                    # return 4  # 返回错误代码 4：数据差异较大
                    pass
                
            if point_light1 is None or point_light2 is None:
                logger.error(f"第 {frame_id} 帧缺少光照信息")
                return 5  # 返回错误代码 5：数据不一致
            else:
                light_difference = (
                    (point_light1["r"] - point_light2["r"]) ** 2 +
                    (point_light1["g"] - point_light2["g"]) ** 2 +
                    (point_light1["b"] - point_light2["b"]) ** 2
                    ) ** 0.5
                
                self.light_differecne_list.append(light_difference)
                if light_difference > self.light_difference_threshold:  # 可以根据需要调整阈值
                    # print(f"第 {frame_id} 帧光照信息不同，差异为 {light_difference}")
                    # return 4  # 返回错误代码 4：数据差异较大
                    pass

        logger.info("drama_json 和 dat_json 的数据一致")
        return 0  # 返回错误代码 0：成功
    
    def plot_differences(self, drm_compare_result_dir="file/drm_compare_results"):

        position_difference_png_path = f"{drm_compare_result_dir}/position_difference.png"
        light_difference_png_path = f"{drm_compare_result_dir}/light_difference.png"
        merged_trajectory_diff_png_path = f"{drm_compare_result_dir}/merged_trajectory_diff.png"


        import matplotlib.pyplot as plt

        frames = list(range(self.points_length))
        
        # --- 保存第一张图：位置差异 ---
        plt.figure() # 创建一个新的图形窗口
        plt.bar(frames, self.point_differecne_list, label='Position Difference')
        plt.axhline(y=self.possition_difference_threshold, color='red', linestyle='--', label=f'Threshold ({self.possition_difference_threshold})')
        plt.xlabel('Frame ID')
        plt.ylabel('Difference')
        plt.title('Position Differences Between drama_json and dat_json')
        plt.legend()
        plt.grid()
        plt.savefig(position_difference_png_path) # 保存为独立文件
        plt.close() # 关闭图形窗口，释放内存
        logger.info(f"已保存 {position_difference_png_path} 图像文件")

        # --- 保存第二张图：光照差异 ---
        plt.figure() # 创建一个新的图形窗口
        plt.bar(frames, self.light_differecne_list, label='Light Difference', color='orange')
        plt.axhline(y=self.light_difference_threshold, color='red', linestyle='--', label=f'Threshold ({self.light_difference_threshold})')
        plt.xlabel('Frame ID')
        plt.ylabel('Difference')
        plt.title('Light Differences Between drama_json and dat_json')
        plt.legend()
        plt.grid()
        plt.savefig(light_difference_png_path) # 保存为独立文件
        plt.close() # 关闭图形窗口，释放内存
        logger.info(f"已保存 {light_difference_png_path} 图像文件")

        # ---保存差异点高亮显示 ---
        # 1. 数据准备与掩码生成
        pos_diff_arr = np.array(self.point_differecne_list)
        light_diff_arr = np.array(self.light_differecne_list)

        # 逻辑或：只要有一个指标超过阈值，即视为异常
        abnormal_mask = (pos_diff_arr > self.possition_difference_threshold) | \
                        (light_diff_arr > self.light_difference_threshold)

        # 2. 创建画布 (修正了变量名，统一使用 fig_3d)
        fig_3d = plt.figure(figsize=(16, 12))

        # --- 绘制轨迹 1 ---
        ax3 = fig_3d.add_subplot(121, projection='3d')
        # 绘制灰色基准轨迹
        ax3.plot(self.xs1, self.ys1, self.zs1, color='gray', alpha=0.3, linewidth=1, label='Normal Trajectory')
        ax3.scatter(self.xs1, self.ys1, self.zs1, c='gray', s=20, alpha=0.3, depthshade=False, label='Normal Points')
        ax3.plot(self.xs2, self.ys2, self.zs2, color='gray', alpha=0.3, linewidth=1)  # 绘制第二条轨迹作为对比
        ax3.scatter(self.xs2, self.ys2, self.zs2, c='gray', s=20, alpha=0.3, depthshade=False)  # 绘制第二条轨迹的点作为对比

        # 绘制红色异常点 (仅当存在异常点时)
        if np.any(abnormal_mask):
            # 确保数据是 numpy 数组以便使用布尔索引
            x1_arr, y1_arr, z1_arr = np.array(self.xs1), np.array(self.ys1), np.array(self.zs1)
            ax3.scatter(x1_arr[abnormal_mask], 
                        y1_arr[abnormal_mask], 
                        z1_arr[abnormal_mask], 
                        c='red', alpha=0.4, s=50, depthshade=False, label='Abnormal Points (Diff > Threshold)', edgecolors='white')

        ax3.set_xlabel('X')
        ax3.set_ylabel('Y')
        ax3.set_zlabel('Z')
        ax3.set_title('Trajectory 1 with Abnormal Points Highlighted')
        ax3.legend()

        # --- 绘制轨迹 2 (修正了 fig_3d_2 -> fig_3d) ---
        ax4 = fig_3d.add_subplot(122, projection='3d')

        ax4.plot(self.xs1, self.ys1, self.zs1, color='gray', alpha=0.4, linewidth=1, label='Trajectory')
        ax4.scatter(self.xs1, self.ys1, self.zs1, c=self.colors1, s=20, depthshade=False)
        ax4.plot(self.xs2, self.ys2, self.zs2, color='gray', alpha=0.4, linewidth=1, label='Trajectory')
        ax4.scatter(self.xs2, self.ys2, self.zs2, c=self.colors2, s=20, depthshade=False)

        ax4.set_xlabel('X')
        ax4.set_ylabel('Y')
        ax4.set_zlabel('Z')
        ax4.set_title('')
        ax4.legend()

        # 3. 保存与关闭
        fig_3d.tight_layout()
        fig_3d.savefig(merged_trajectory_diff_png_path, dpi=300) # 建议增加 dpi 以获得清晰图片
        plt.close()

        logger.info(f"✅ 已保存 {merged_trajectory_diff_png_path} 图像文件")

        return [position_difference_png_path, light_difference_png_path, merged_trajectory_diff_png_path]


if __name__ == "__main__":
    drama_json = "drama_files/0422-L10P2_drone_1.json"
    dat_json = "dat/L10P2.json"
    
    comparer = DrmCompare(drama_json, dat_json)
    error_code = comparer.compare_one_drone_data()
    print(f"比较结果：{ERROR_CODE[error_code]} (错误代码 {error_code})")
    
    if error_code == 0:
        comparer.plot_differences(drm_compare_result_dir="drm_compare_results")

            
            
        
