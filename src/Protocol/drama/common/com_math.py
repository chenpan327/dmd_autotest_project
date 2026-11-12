#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import math
import random
import numpy as np
try:
    from . import com_func
except:
    import com_func


class CircumCircle:
    def __init__(self, triangle):
        p1 = triangle.edges[0].points[0]
        p2 = triangle.edges[1].points[0]
        p3 = triangle.edges[2].points[0]

        side1 = triangle.edges[0].point_distance
        side2 = triangle.edges[1].point_distance
        side3 = triangle.edges[2].point_distance

        self.circum_center = self.GetCircumCenter(p1, p2, p3)

        self.radius = self.GetCircumRadius(side1, side2, side3)

    def GetCircumRadius(self, side1, side2, side3):
        s = (side1 + side2 + side3) / 2
        area = math.sqrt(s * (s - side1) * (s - side2) * (s - side3))
        if area == 0:
            return 0
        return (side1 * side2 * side3) / (4 * area)

    def GetCircumCenter(self, p1, p2, p3):
        # a1, b1, c1 = self.GetLineEquationFromPoints(p1, p2)
        # a2, b2, c2 = self.GetLineEquationFromPoints(p2, p3)
        #
        # a1, b1, c1 = self.GetPerpendicularBisectorLineEquation(p1, p2, a1, b1, c1)
        # a2, b2, c2 = self.GetPerpendicularBisectorLineEquation(p2, p3, a2, b2, c2)
        #
        # circum_center = self.GetLinesIntersection(a1, b1, c1, a2, b2, c2)
        x1, y1, z1 = p1.x, p1.y, p1.z
        x2, y2, z2 = p2.x, p2.y, p2.z
        x3, y3, z3 = p3.x, p3.y, p3.z

        a1 = (y1 * z2 - y2 * z1 - y1 * z3 + y3 * z1 + y2 * z3 - y3 * z2)
        b1 = -(x1 * z2 - x2 * z1 - x1 * z3 + x3 * z1 + x2 * z3 - x3 * z2)
        c1 = (x1 * y2 - x2 * y1 - x1 * y3 + x3 * y1 + x2 * y3 - x3 * y2)
        d1 = -(x1 * y2 * z3 - x1 * y3 * z2 - x2 * y1 * z3 + x2 * y3 * z1 + x3 * y1 * z2 - x3 * y2 * z1)

        a2 = 2 * (x2 - x1)
        b2 = 2 * (y2 - y1)
        c2 = 2 * (z2 - z1)
        d2 = x1 * x1 + y1 * y1 + z1 * z1 - x2 * x2 - y2 * y2 - z2 * z2

        a3 = 2 * (x3 - x1)
        b3 = 2 * (y3 - y1)
        c3 = 2 * (z3 - z1)
        d3 = x1 * x1 + y1 * y1 + z1 * z1 - x3 * x3 - y3 * y3 - z3 * z3

        center = [0, 0, 0]

        center[0] = -(b1 * c2 * d3 - b1 * c3 * d2 - b2 * c1 * d3 + b2 * c3 * d1 + b3 * c1 * d2 - b3 * c2 * d1) \
                    / (a1 * b2 * c3 - a1 * b3 * c2 - a2 * b1 * c3 + a2 * b3 * c1 + a3 * b1 * c2 - a3 * b2 * c1)
        center[1] = (a1 * c2 * d3 - a1 * c3 * d2 - a2 * c1 * d3 + a2 * c3 * d1 + a3 * c1 * d2 - a3 * c2 * d1) \
                    / (a1 * b2 * c3 - a1 * b3 * c2 - a2 * b1 * c3 + a2 * b3 * c1 + a3 * b1 * c2 - a3 * b2 * c1)
        center[2] = -(a1 * b2 * d3 - a1 * b3 * d2 - a2 * b1 * d3 + a2 * b3 * d1 + a3 * b1 * d2 - a3 * b2 * d1) \
                    / (a1 * b2 * c3 - a1 * b3 * c2 - a2 * b1 * c3 + a2 * b3 * c1 + a3 * b1 * c2 - a3 * b2 * c1)

        return Point(center[0], center[1], center[2])

    def GetLineEquationFromPoints(self, p1, p2):
        a = p2.y - p1.y
        b = p1.x - p2.x
        c = a * p1.x + b * p1.y
        return a, b, c

    def GetPerpendicularBisectorLineEquation(self, p1, p2, a, b, c):
        mid_point = (p1 + p2) / 2
        c = -b * mid_point.x + a * mid_point.y
        temp = a
        a = -b
        b = temp
        return a, b, c

    def GetLinesIntersection(self, a1, b1, c1, a2, b2, c2):
        determinant = a1 * b2 - a2 * b1
        if (determinant == 0):
            return None
        else:
            x = (b2 * c1 - b1 * c2) // determinant
            y = (a1 * c2 - a2 * c1) // determinant
            return Point(x, y, 1)

    def IsPointInside(self, point):
        dist = euclidean_distance([point.x, point.y, point.z], [self.circum_center.x, self.circum_center.y, self.circum_center.z])
        return dist < self.radius

    def __repr__(self):
        return f"Circum Circle - Center: {self.circum_center}, Radius: {self.radius}"

    def __str__(self):
        return self.__repr__()


class Point:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def __repr__(self):
        return f"\nPoint - X: {self.x}, Y: {self.y}, Z: {self.z} "

    def __str__(self):
        return self.__repr__()

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y and self.z == other.z

    def __add__(self, other):
        return Point(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other):
        return Point(self.x - other.x, self.y - other.y, self.z - other.z)

    def __truediv__ (self, value):
        return Point(self.x/value, self.y/value, self.z/value)


class Edge:
    def __init__(self, point1, point2):
        self.points = []
        self.points.append(point1)
        self.points.append(point2)

        if point1 is None or point2 is None:
            print(point1, point2)
        self.point_distance = euclidean_distance([point1.x, point1.y, point1.z], [point2.x, point2.y, point2.z])
        if self.point_distance < (abs(point1.x - point2.x)) or self.point_distance < (abs(point1.y - point2.y)) or self.point_distance < (abs(point1.z - point2.z)):
            print(point1, point2)
            print(self.point_distance)

    def __str__(self):
        out_str = "\nEdge - "

        for point in self.points:
            out_str += str(point)

        return out_str

    def __eq__(self, other):
        condition1 = self.points[0] == other.points[0] and self.points[1] == other.points[1]
        condition2 = self.points[0] == other.points[1] and self.points[1] == other.points[0]

        return condition1 or condition2

class Triangle:
    def __init__(self, edge1, edge2, edge3):
        self.edges = []
        self.edges.append(edge1)
        self.edges.append(edge2)
        self.edges.append(edge3)

        self.circum_circle = CircumCircle(self)

    def IsInCircumCircle(self, point):
        return self.circum_circle.IsPointInside(point)

    def __repr__(self):
        out_str = "Triangle - "

        for edge in self.edges:
            out_str += str(edge)

        return repr(out_str)

    def __str__(self):
        return self.__repr__()


class DelaunayTriangulation:
    def __init__(self):
        self.mesh = []
        self.points = []

    def Triangulate(self):
        self.mesh = []
        super_triangle = self.CalculateSuperTriangle()

        triangles = [super_triangle]

        for point in self.points:
            triangles = self.AddPointToMesh(point, triangles)

        triangles = self.RemoveSuperTriangle(triangles, super_triangle)

        self.mesh = triangles

    def regular(self):
        count = 0
        total_flag = [0 for i in range(len(self.points))]

        result = list()

        for m in self.mesh:
            tmp = list()
            for e in m.edges:
                tmp.append([e.points[0].x, e.points[0].y, e.points[0].z])
                tmp.append([e.points[1].x, e.points[1].y, e.points[1].z])
            tmp = com_func.remove_duplicate_sublists2(tmp)

            if len(tmp) == 3:
                flag = [-1, -1, -1]
                new_count = 0
                has_count = 0
                for i in range(len(self.points)):
                    for t in range(3):
                        if is_close(tmp[t][0], self.points[i].x) and \
                                is_close(tmp[t][1], self.points[i].y) and \
                                is_close(tmp[t][2], self.points[i].z):
                            flag[t] = i
                            has_count += 1
                            if total_flag[i] == 0:
                                new_count += 1
                            total_flag[i] += 1
                    if has_count == 3:
                        break

                if new_count > 0:
                    # if True:
                    count += new_count
                    small_triangle = list()
                    small_triangle.append(self.points[flag[0]])
                    small_triangle.append(self.points[flag[1]])
                    small_triangle.append(self.points[flag[2]])
                    result.append(small_triangle)
        return result

    def AddPointToMesh(self, point, triangles):
        edges = []
        good_triangles = []

        for triangle in triangles:
            if triangle.IsInCircumCircle(point):
                edges += triangle.edges

            else:
                if triangle.circum_circle.radius > 0:
                    good_triangles.append(triangle)
                else:
                    print(f"bad triangle: {triangle}")

        edges = self.GetUniqueEdges(edges)

        for edge in edges:
            e1 = Edge(edge.points[0], edge.points[1])
            e2 = Edge(edge.points[1], point)
            e3 = Edge(point, edge.points[0])

            triangle = Triangle(e1, e2, e3)

            good_triangles.append(triangle)

        return good_triangles

    def GetUniqueEdges(self, edges):
        unique_edges = []

        for i in range(len(edges)):
            edge1 = edges[i]
            is_unique_edge = True
            for j in range(len(edges)):
                edge2 = edges[j]
                if i != j and edge1 == edge2:
                    is_unique_edge = False
                    break

            if is_unique_edge:
                unique_edges.append(edge1)

        return unique_edges

    def RemoveSuperTriangle(self, triangles, super_triangle):
        mesh_triangles = []

        super_tri_p1 = super_triangle.edges[0].points[0]
        super_tri_p2 = super_triangle.edges[1].points[0]
        super_tri_p3 = super_triangle.edges[2].points[0]

        for triangle in triangles:
            p1 = triangle.edges[0].points[0]
            p2 = triangle.edges[1].points[0]
            p3 = triangle.edges[2].points[0]

            if not (p1 == super_tri_p1 or p1 == super_tri_p2 or p1 == super_tri_p3 or
                    p2 == super_tri_p1 or p2 == super_tri_p2 or p2 == super_tri_p3 or
                    p3 == super_tri_p1 or p3 == super_tri_p2 or p3 == super_tri_p3):
                mesh_triangles.append(triangle)

        return mesh_triangles

    def AddPoint(self, point):
        self.points.append(point)

    def CalculateSuperTriangle(self):
        x_min = 1000
        x_max = 0
        y_min = 1000
        y_max = 0
        z_min = 1000
        z_max = 0

        for point in self.points:
            x_max = max(x_max, point.x)
            x_min = min(x_min, point.x)
            y_max = max(y_max, point.y)
            y_min = min(y_min, point.y)
            z_max = max(z_max, point.z)
            z_min = min(z_min, point.z)

        dx = (x_max - x_min) * 10
        dy = (y_max - y_min) * 10
        dz = (z_max - z_min) * 10

        p1 = Point(x=x_min - dx, y=y_min - dy * 3, z=z_min - dz)
        p2 = Point(x=x_min - dx, y=y_max + dy, z=z_min + dz)
        p3 = Point(x=x_max + dx * 3, y=y_max + dy, z=z_max + dz * 3)
        # p1 = Point(x = x_min - dx    , y = y_min - dy * 3, z = 1)
        # p2 = Point(x = x_min - dx    , y = y_max + dy    , z = 1)
        # p3 = Point(x = x_max + dx * 3, y = y_max + dy    , z = 1)
        p1 = Point(x=x_min - dx * 3, y=y_min - dy * 3, z=z_min - dz * 3)
        p2 = Point(x=x_max + dx * 3, y=y_max + dy * 3, z=z_max + dz * 3)
        p3 = Point(x=x_max + dx * 3, y=y_max + dy * 3, z=z_min - dz * 3)

        e1 = Edge(p1, p2)
        e2 = Edge(p2, p3)
        e3 = Edge(p3, p1)

        return Triangle(e1, e2, e3)

# matrix
def solve_linear_equations(A, B, index=None, value=None):
    # check the dimension
    if len(A[0]) != len(B):
        raise ValueError("The dimensions of matrix A and vector B do not match.")

    # coefficient matrix rows and columns
    num_rows = len(A)
    num_cols = len(A[0])

    if num_rows > 2:
        # if in a plane
        plane_flag = [True for _ in range(num_cols)]
        for col in range(num_cols):
            mask = A[0][col]
            for row in range(num_rows):
                if A[row][col] != mask:
                    plane_flag[col] = False

        if True in plane_flag:
            del_idx = plane_flag.index(True)
            del A[del_idx]
            del B[del_idx]

            for row in A:
                del row[del_idx]

            # return [solve_linear_equations(A, B), del_idx]
            return solve_linear_equations(A, B, index=del_idx, value=value)

    X = [0] * num_cols

    # augmented matrix
    augmented_matrix = [row + [B[i]] for i, row in enumerate(A)]

    # Gaussian elimination
    for col in range(num_cols):
        # find the non-zero column
        nonzero_row = None
        for row in range(col, num_rows):
            if augmented_matrix[row][col] != 0:
                nonzero_row = row
                break

        if nonzero_row is None:
            raise ValueError("The linear equations have no solution.")

        augmented_matrix[col], augmented_matrix[nonzero_row] = augmented_matrix[nonzero_row], augmented_matrix[col]

        pivot = augmented_matrix[col][col]
        augmented_matrix[col] = [entry / pivot for entry in augmented_matrix[col]]

        for row in range(num_rows):
            if row != col:
                multiplier = augmented_matrix[row][col]
                augmented_matrix[row] = [entry - multiplier * augmented_matrix[col][i] for i, entry in
                                         enumerate(augmented_matrix[row])]

    for row in range(num_rows):
        X[row] = augmented_matrix[row][-1]

    if index is not None:
        X.insert(index, value)

    return X


def matrix_multiply(matrix1, matrix2):
    # get rows and columns of matrices
    rows1, cols1 = len(matrix1), len(matrix1[0])
    rows2, cols2 = len(matrix2), len(matrix2[0])

    # ensure the format of two matrices
    if cols1 != rows2:
        raise ValueError("'''Matrix_1's columns doesn't equal matrix_2's rows'''")

    # create result matrix
    result = [[0] * cols2 for _ in range(rows1)]

    # do multiply
    for i in range(rows1):
        for j in range(cols2):
            for k in range(cols1):
                result[i][j] += matrix1[i][k] * matrix2[k][j]

    return result


def vector_dot_product(vector1, vector2, check=True):
    # calculate the dot product result from two vectors
    if check:
        if len(vector1) != len(vector2):
            raise ValueError("'''The dimensions of two input vectors are different'''")

    return sum(vector1[i] * vector2[i] for i in range(len(vector1)))


def vector_cross_product(vector1, vector2, check=True):
    # calculate the cross product result from two vectors
    # notice: only used in 3 dimensions condition
    if check:
        if len(vector1) != len(vector2):
            raise ValueError("'''The dimensions of two input vectors are different'''")
        if len(vector1) != 3:
            raise ValueError("'''Function can only accept 3 dimension vector'''")
    return [vector1[1] * vector2[2] - vector1[2] * vector2[1],
            vector1[2] * vector2[0] - vector1[0] * vector2[2],
            vector1[0] * vector2[1] - vector1[1] * vector2[0]]


def is_vectors_collinear(vector1, vector2):
    # Judge two vectors are collinear

    if len(vector1) != len(vector2):
        raise ValueError("'''The dimensions of two input vectors are different'''")

    if len(vector1) == 2:
        if vector1[0] == vector2[0] == 0 or vector1[1] == vector2[1] == 0:
            return True
        return True if vector1[0] / vector2[0] == vector1[1] / vector2[1] else False

    if len(vector1) == 3:
        cross_product = vector_cross_product(vector1, vector2)

        modulus1 = euclidean_distance(vector1, [0, 0, 0])
        modulus2 = euclidean_distance(vector2, [0, 0, 0])

        if all(i == 0 for i in cross_product) or modulus1 == 0 or modulus2 == 0:
            return True
        else:
            return False

    else:
        raise ValueError("'''Dimensions other than 2 and 3 dimensions are not supported temporarily'''")


def vector_degree(vector1, vector2):
    dot_product = sum(a * b for a, b in zip(vector1, vector2))

    # Calculate cross product
    cross_product = [vector1[1] * vector2[2] - vector1[2] * vector2[1],
                     vector1[2] * vector2[0] - vector1[0] * vector2[2],
                     vector1[0] * vector2[1] - vector1[1] * vector2[0]]

    # Calculate magnitudes
    magnitude_A = math.sqrt(sum(a * a for a in vector1))
    magnitude_B = math.sqrt(sum(b * b for b in vector2))
    magnitude_C = math.sqrt(sum(c * c for c in cross_product))

    # Calculate cosθ and sinθ
    cos_theta = dot_product / (magnitude_A * magnitude_B)
    sin_theta = magnitude_C / (magnitude_A * magnitude_B)

    # Calculate the angle θ using arctan2
    angle_rad = math.atan2(sin_theta, cos_theta)

    # Convert the angle from radians to degrees
    angle_deg = math.degrees(angle_rad)
    return angle_deg

def project_point_on_line_segment(point, normal_vector):
    x = point[0]
    y = point[1]
    a1 = normal_vector[0][0]
    b1 = normal_vector[0][1]
    a2 = normal_vector[1][0]
    b2 = normal_vector[1][1]
    # 计算向量 D 和 P
    dx, dy = a2 - a1, b2 - b1
    px, py = x - a1, y - b1

    # 计算 D 的长度平方
    d_squared = dx * dx + dy * dy

    # 计算点在向量 D 上的投影比例
    projection_ratio = (px * dx + py * dy) / d_squared

    # 计算投影点在 D 上的实际位置
    proj_x = a1 + projection_ratio * dx
    proj_y = b1 + projection_ratio * dy

    # 计算投影长度
    proj_length_on_D = projection_ratio * math.sqrt(d_squared)

    # 判断投影点是否在D范围内
    if projection_ratio < 0:
        return -proj_length_on_D  # 投影点在起点之前
    else:
        return proj_length_on_D  # 投影点在D的范围内

# --------------------------------------------------------------------------------------------
# point
def euclidean_distance(point1, point2):
    # calculate Euclidean distance between two points

    # the dimension of two points is same
    if len(point1) != len(point2):
        raise ValueError("'''The dimensions of the two input points are different'''")

    if len(point1) == 1:
        return point2[0] - point1[0]

    # sqrt( (x1-x2)**2 + (y1-y2)**2 + … )
    return math.sqrt(
        sum((point1[i] - point2[i]) ** 2 for i in range(len(point1)))
    )


def get_vertical_plane_from_points(point1, point2):
    # Ax + By + Cz = D
    mid = ((point1[0] + point2[0]) / 2, (point1[1] + point2[1]) / 2, (point1[2] + point2[2]) / 2)
    normal = [point1[0] - point2[0], point1[1] - point2[1], point1[2] - point2[2]]

    # (A, B, C), D
    return [[normal[0], normal[1], normal[2]],
            normal[0] * mid[0] + normal[1] * mid[1] + normal[2] * mid[2]
            ]


def make_vector(point1, point2):
    return [
        point1[i] - point2[i] for i in range(len(point1))
    ]



# --------------------------------------------------------------------------------------------
# number
def degree_2_pi(degree):
    return (degree * 2 * math.pi) / 360


def pi_2_degree(degree):
    return (degree * 360) / (2 * math.pi)


def eliminate_deviation_equal(a, b, deviation=5):
    if round(a, deviation) == round(b, deviation):
        return True
    else:
        return False
    # return True if abs(a - b) < deviation else False


def random_sample(lst, n):
    if n > len(lst):
        raise ValueError("'''You wanted is bigger than the list has'''")
    return random.sample(lst, n)


def get_degree(vector1, vector2):
    # 360
    if len(vector1) != len(vector2) or len(vector1) == 1:
        return None

    if len(vector1) == 2:
        # 计算向量的点积
        dot_product = vector1[0] * vector2[0] + vector1[1] * vector2[1]

        # 计算向量的模
        magnitude1 = math.sqrt(vector1[0] ** 2 + vector1[1] ** 2)
        magnitude2 = math.sqrt(vector2[0] ** 2 + vector2[1] ** 2)

        # 使用点积公式计算角度的余弦值
        cos_theta = dot_product / (magnitude1 * magnitude2)

        # 计算角度（弧度）
        angle_radians = math.acos(cos_theta)

        # 计算向量的叉积
        cross_product = vector1[0] * vector2[1] - vector1[1] * vector2[0]

        # 将角度转换为度数
        angle_degrees = math.degrees(angle_radians)

        # 根据叉积的符号来确定角度的方向
        if cross_product < 0:
            angle_degrees = 360 - angle_degrees

        return angle_degrees


def is_close(a, b, scale=1e-05):
    return (abs(a - b) <= scale)


def python_std(a):
    mean = sum(a) / len(a)

    variance_sum = sum((x - mean) ** 2 for x in a)

    variance = variance_sum / len(a)

    return math.sqrt(variance)


def zeros(n, dtype=int):
    return [dtype(0)] * n

def constrain_float(amt, low, high):
    if math.isnan(amt):
        return (low + high) * 0.5
    return low if amt < low else high if amt > high else amt


def align_frame(cur_frame, interval, front=False):
    cur_frame = int(cur_frame)
    if cur_frame % interval == 1:
        return int(cur_frame)

    if cur_frame % interval == 0:
        if front:
            return int(cur_frame - interval + 1)
        else:
            return int(cur_frame + 1)

    offset = cur_frame % interval
    if front:
        result = cur_frame - offset + 1
    else:
        result = cur_frame + (interval - offset) + 1
    return result


class Plane:
    def __init__(self, p1, p2, p3):
        self.p1 = p1
        self.p2 = p2
        self.p3 = p3
        self.vector_1 = list()
        self.vector_2 = list()
        self.normal_vector = None  # 初始化为None
        self.is_plane = self.judge_is_plane()
        self.plane_equation = self.calculate_plane_equation()

    def judge_is_plane(self):
        # 计算两个向量
        self.vector_1 = [self.p1[0] - self.p2[0], self.p1[1] - self.p2[1], self.p1[2] - self.p2[2]]
        self.vector_2 = [self.p1[0] - self.p3[0], self.p1[1] - self.p3[1], self.p1[2] - self.p3[2]]

        # 计算叉积
        cross_product = [
            self.vector_1[1] * self.vector_2[2] - self.vector_1[2] * self.vector_2[1],
            self.vector_1[2] * self.vector_2[0] - self.vector_1[0] * self.vector_2[2],
            self.vector_1[0] * self.vector_2[1] - self.vector_1[1] * self.vector_2[0]
        ]

        # 判断是否共线：如果叉积为零向量，则三点共线
        if cross_product == [0, 0, 0]:
            return False  # 三点共线，不构成平面
        else:
            self.normal_vector = cross_product  # 直接赋值给normal_vector
            return True  # 三点不共线，构成平面

    def calculate_plane_equation(self):
        if not self.is_plane:
            return None  # 如果不构成平面，返回None

        # 平面方程的一般形式：Ax + By + Cz + D = 0
        # 法向量的分量就是A, B, C
        A, B, C = self.normal_vector
        # 代入点p1计算D
        D = -(A * self.p1[0] + B * self.p1[1] + C * self.p1[2])
        return (A, B, C, D)

    def is_point_on_plane(self, p):
        if not self.is_plane:
            return None  # 如果不构成平面，返回None

        # 判断点p是否在平面上：代入平面方程，检查是否满足Ax + By + Cz + D = 0
        A, B, C, D = self.plane_equation
        x, y, z = p
        return abs(A * x + B * y + C * z + D) < 1e-6  # 考虑浮点数精度误差

    def dis_to_plane(self, p):
        if not self.is_plane:
            return None
        A, B, C, D = self.plane_equation
        x, y, z = p
        return abs(A * x + B * y + C * z + D) / (A ** 2 + B ** 2 + C ** 2) ** 0.5

def deg2rad(deg):
    """角度转弧度"""
    return deg * math.pi / 180.0

def rad2deg(rad):
    """弧度转角度"""
    return rad * 180.0 / math.pi


def gimbal_compensate_yaw(old_yaw_deg, new_yaw_deg, old_pitch_deg, old_roll_deg):

    if old_yaw_deg == new_yaw_deg:
        return old_pitch_deg, old_roll_deg
    """
    飞机 yaw 变化时，计算云台新的 pitch 和 roll，使云台朝向在世界空间中保持不变。

    约定：
    - pitch=0, roll=0: 云台指向机头正对方向
    - pitch=90, roll=0: 云台垂直指向地面
    - pitch=180, roll=0: 云台指向机尾
    - pitch=90, roll=90: 云台指向飞机正右侧
    - pitch=90, roll=-90: 云台指向飞机正左侧
    - yaw=0: 机头指向北方，yaw=90: 机头指向正西

    输入：old_yaw, new_yaw, old_pitch, old_roll（度）
    输出：(new_pitch_deg, new_roll_deg)
    """
    y0 = deg2rad(old_yaw_deg)
    y1 = deg2rad(new_yaw_deg)
    p0 = deg2rad(old_pitch_deg)
    r0 = deg2rad(old_roll_deg)

    # 机体系：X 前(机头), Y 右, Z 上
    # 由用户约定可反推出方向向量表达式：
    # p=0,r=0   -> ( 1,  0,  0) 前
    # p=90,r=0  -> ( 0,  0, -1) 下
    # p=180,r=0 -> (-1,  0,  0) 后
    # p=90,r=90 -> ( 0,  1,  0) 右
    # 因此：
    # x = cos(p)
    # y = sin(p) * sin(r)
    # z = -sin(p) * cos(r)
    sp, cp = math.sin(p0), math.cos(p0)
    sr, cr = math.sin(r0), math.cos(r0)
    xb = cp
    yb = sp * sr
    zb = -sp * cr

    # 世界系：X 北, Y 东, Z 上
    # yaw=90 时机头朝西，因此 body -> world 使用 Rz(-yaw)
    cy0, sy0 = math.cos(y0), math.sin(y0)
    xw = xb * cy0 + yb * sy0
    yw = -xb * sy0 + yb * cy0
    zw = zb

    # 在新 yaw 下，把世界方向转回新的机体系：world -> body 使用 Rz(+yaw)
    cy1, sy1 = math.cos(y1), math.sin(y1)
    xb1 = xw * cy1 - yw * sy1
    yb1 = xw * sy1 + yw * cy1
    zb1 = zw

    # 由方向向量反解回用户定义的 pitch / roll
    horiz_norm = math.sqrt(yb1 * yb1 + zb1 * zb1)
    pitch_out = rad2deg(math.atan2(horiz_norm, xb1))

    if horiz_norm < 1e-10:
        roll_out = 0.0
    else:
        roll_out = rad2deg(math.atan2(yb1, -zb1))

    return pitch_out, roll_out

print(gimbal_compensate_yaw(0, 90, 40, 0))