import math
from model.vec2 import Vec2
from typing import Dict, List, Optional
import numpy as np


def unit_vector(vector):
    return vector / np.linalg.norm(vector)


def find_distance(pos_1: Vec2, pos_2: Vec2):
    return math.sqrt((pos_1.x - pos_2.x) ** 2 + (pos_1.y - pos_2.y) ** 2)


def find_closest_point(main_point: Vec2, points: List[Vec2]):
    closest_dist = math.inf
    closest_id = None
    
    for x, (point) in enumerate(points):
        dist = find_distance(main_point, point)
        if dist < closest_dist:
            closest_dist = dist
            closest_id = x
            
    return closest_id, closest_dist
