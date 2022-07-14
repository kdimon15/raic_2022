from asyncio import constants
from audioop import add
from distutils.archive_util import make_archive
from fileinput import close
from locale import currency
from optparse import Option
from re import S

from numpy import isin
from model.game import Game
from model.loot import Loot
from model.order import Order
from model.unit import Unit
from model.unit_order import UnitOrder
from model.constants import Constants
from model.vec2 import Vec2
from model.action_order import ActionOrder
from typing import Dict, List, Optional
from debug_interface import DebugInterface
from model.weapon_properties import WeaponProperties
from model.item import Weapon, Ammo, ShieldPotions
from model import Zone
from debugging import Color
import math
import numpy as np
from utils import unit_vector, find_closest_point, find_distance


"""
Улучшить проверку спины, чтоб не баговало
Уворот юнита
"""


class MyStrategy:

    def __init__(self, constants: Constants):
        self.my_unit_id: int = None
        self.current_mission: str = 'kill'
        self.game_constants: Constants = constants
        
        self.loot_ids = []
        self.ammo: List[Loot] = []
        self.guns: List[Loot] = []
        self.shields: List[Loot] = []
        self.pickup_ids: List[int] = []
        
        self.game: Optional[Game]
        self.my_unit: Optional[Unit]
        self.add_action: Optional[ActionOrder]
        
        self.closest_gun: Optional[Loot]
        self.gun_dist: Optional[int]
        self.closest_shield: Optional[Loot]
        self.shield_dist: Optional[int]
        self.closest_ammo: Optional[Loot]
        self.ammo_dist: Optional[int]
        
        self.closest_enemy: Optional[Unit]
        self.enemy_dist: Optional[int]
        
        self.current_weapon: Optional[WeaponProperties]
        self.busy: int = -1
        
        self.enemy_sounds = []
        self.back_sounds = []
        self.current_angle: Optional[int]
        self.closest_back: Optional[Vec2]
        self.go_center = -1
        
        self.target_direction: Optional[Vec2] = Vec2(1, 0)

    def get_around_direction(self):
        if self.target_direction.x == np.round(self.my_unit.direction.x, 3) and self.target_direction.y == np.round(self.my_unit.direction.y, 3):
            if self.target_direction.x == 1 and self.target_direction.y == 0:
                self.target_direction = Vec2(0, -1)
            elif self.target_direction.x == 0 and self.target_direction.y == -1:
                self.target_direction = Vec2(-1, 0)
            elif self.target_direction.x == -1 and self.target_direction.y == 0:
                self.target_direction = Vec2(0, 1)
            elif self.target_direction.x == 0 and self.target_direction.y == 1:
                self.target_direction = Vec2(1, 0)
        return self.target_direction
            
        
        
    def make_move(self, command: str):
        if command == 'Идти в центр':
            if find_distance(self.game.zone.next_center, self.my_unit.position) < 5:
                print('in center', self.my_unit.direction)
                return self.make_order(
                            Vec2(0, 0),
                            self.get_around_direction(),
                            action=self.add_action
                        )
            else:
                return self.make_order(
                            Vec2(self.game.zone.next_center.x-self.my_unit.position.x,
                                self.game.zone.next_center.y-self.my_unit.position.y),
                            Vec2(self.game.zone.next_center.x-self.my_unit.position.x, 
                                self.game.zone.next_center.y-self.my_unit.position.y),
                            action=self.add_action
                        )
                
        elif command == 'Патроны':
            if self.ammo_dist > 0.5:
                return self.make_order(
                        Vec2((self.closest_ammo.position.x-self.my_unit.position.x)*5,
                                (self.closest_ammo.position.y-self.my_unit.position.y)*5),
                        # Vec2(self.closest_ammo.position.x-self.my_unit.position.x,
                        #         self.closest_ammo.position.y-self.my_unit.position.y),
                        self.get_around_direction(),
                        action=self.add_action
                    )
            else:
                return self.make_order(
                    Vec2(0, 0),
                    Vec2(0, 0),
                    action='pickup',
                    pickup_id=self.closest_ammo.id
                )
        
        elif command == 'Оружие':
            if self.gun_dist > 0.5:
                return self.make_order(
                        Vec2((self.closest_gun.position.x-self.my_unit.position.x)*5,
                                (self.closest_gun.position.y-self.my_unit.position.y)*5),
                        Vec2(self.closest_gun.position.x-self.my_unit.position.x,
                                self.closest_gun.position.y-self.my_unit.position.y),
                        action=self.add_action
                    )
            else:
                return self.make_order(
                    Vec2(0, 0),
                    Vec2(0, 0),
                    action='pickup',
                    pickup_id=self.closest_gun.id
                )
        elif command == 'Щит':
            if self.shield_dist > 0.5:
                return self.make_order(
                        Vec2((self.closest_shield.position.x-self.my_unit.position.x)*5,
                                (self.closest_shield.position.y-self.my_unit.position.y)*5),
                        # Vec2(self.closest_shield.position.x-self.my_unit.position.x,
                        #         self.closest_shield.position.y-self.my_unit.position.y),
                        self.get_around_direction(),
                        action=self.add_action
                    )
            else:
                return self.make_order(
                    Vec2(0, 0),
                    Vec2(0, 0),
                    action='pickup',
                    pickup_id=self.closest_shield.id
                )
                
    def check_distance(self, loot: Loot):
        dist = math.sqrt((self.game.zone.current_center.x - loot.position.x)**2+(self.game.zone.current_center.y - loot.position.y)**2)
        return dist < self.game.zone.current_radius
    
    
    def find_angle(self, position: Vec2):
        v1_u = unit_vector((self.my_unit.direction.x, self.my_unit.direction.y))
        v2_u = unit_vector((position.x-self.my_unit.position.x, position.y-self.my_unit.position.y))
        return np.arccos(np.clip(np.dot(v1_u, v2_u), -1.0, 1.0))
        
        
    def get_order(self, game: Game, debug_interface: Optional[DebugInterface]):
        
        orders = {}
        enemies: List[Unit] = []

        for unit in game.units:
            if unit.player_id != game.my_id:
                enemies.append(unit)
            else:
                self.my_unit = unit
                self.current_weapon = self.game_constants.weapons[unit.weapon]
                
        self.game = game
        self.current_angle = self.game_constants.field_of_view - (self.game_constants.field_of_view - self.current_weapon.aim_field_of_view) * self.my_unit.aim
        self.current_angle = self.current_angle * np.pi / 180 / 2

        self.enemy_sounds = [x for x in self.enemy_sounds if x[0] >= game.current_tick]
        for x in game.sounds:
            if x.type_index <= 3:
                self.enemy_sounds.append((self.game.current_tick+100, x.position))
                
        for x in range(len(self.enemy_sounds)-1, -1, -1):
            if self.find_angle(self.enemy_sounds[x][1]) < self.current_angle - 0.1:
                self.enemy_sounds.pop(x)
                
        self.back_sounds = [x[1] for x in self.enemy_sounds if self.find_angle(x[1]) > self.current_angle]
        
        print(len(self.enemy_sounds), len(self.back_sounds))
        
        if len(self.back_sounds):
            back_sounds_dist = min([find_distance(x, self.my_unit.position) for x in self.back_sounds])
            self.closest_back = self.back_sounds[np.argmin(back_sounds_dist)]
        else:
            back_sounds_dist = math.inf


        tmp = [x for x in game.loot if isinstance(x.item, Weapon) and x.item.type_index==2 and x.id not in self.pickup_ids and x.id not in self.loot_ids]
        for x in tmp:
            if x.id not in self.loot_ids:
                self.loot_ids.append(x.id)
                self.guns.append(x)
                
        self.guns = [x for x in self.guns if x.id not in self.pickup_ids and self.check_distance(x)]
        
        if len(self.guns):
            gun_id, self.gun_dist = find_closest_point(self.my_unit.position, [x.position for x in self.guns])
            self.closest_gun = self.guns[gun_id]
        else:
            self.closest_gun, self.gun_dist = None, math.inf
        

        tmp = [x for x in game.loot if isinstance(x.item, Ammo) and x.id not in self.pickup_ids]
        for x in tmp:
            if x.id not in self.loot_ids:
                self.loot_ids.append(x.id)
                self.ammo.append(x)
        
        self.ammo = [x for x in self.ammo if x.id not in self.pickup_ids and self.check_distance(x)]
        
        cur_ammo = [x for x in self.ammo if x.item.weapon_type_index == self.my_unit.weapon]
        if len(cur_ammo):
            ammo_id, self.ammo_dist = find_closest_point(self.my_unit.position, [x.position for x in cur_ammo])
            self.closest_ammo = cur_ammo[ammo_id]
        else:
            self.closest_ammo, self.ammo_dist = None, math.inf
        
        
        tmp = [x for x in game.loot if isinstance(x.item, ShieldPotions) and x.id not in self.pickup_ids]
        for x in tmp:
            if x.id not in self.loot_ids:
                self.loot_ids.append(x.id)
                self.shields.append(x)
                
        self.shields = [x for x in self.shields if x.id not in self.pickup_ids and self.check_distance(x)]
        
        if len(self.shields):
            # for x in self.shields:
            #     debug_interface.add_placed_text(x.position, str(np.round(find_distance(x.position, self.my_unit.position), 3)), Vec2(0.5, 0.5), 0.3, Color(255, 0, 0, 1))
            
            shield_id, self.shield_dist = find_closest_point(self.my_unit.position, [x.position for x in self.shields])
            self.closest_shield = self.shields[shield_id]
        else:
            self.closest_shield, self.shield_dist = None, math.inf
        
        if len(enemies):
            enemy_id, self.enemy_dist = find_closest_point(self.my_unit.position, [x.position for x in enemies])
            self.closest_enemy: Unit = enemies[enemy_id]
        else:
            self.closest_enemy, self.enemy_dist = None, math.inf
            
        self.need_shield = self.my_unit.shield < self.game_constants.max_shield or self.my_unit.shield_potions == 0
        self.need_ammo = self.my_unit.ammo[self.my_unit.weapon] < self.current_weapon.max_inventory_ammo
        self.need_health = self.my_unit.health < self.game_constants.unit_health

        
        if self.my_unit.shield_potions > 0 and self.my_unit.shield != self.game_constants.max_shield:
            self.add_action = 'shield_potion'
        else:
            self.add_action = None
            
        
        # if len(game.projectiles) > 0:
        #     print('_____________')
        #     print(self.my_unit.position, self.my_unit.direction)
        #     print(game.projectiles[0])
        #     print(self.my_unit.velocity)
        #     print('+++++++')
            

        if self.go_center > game.current_tick:
            orders[self.my_unit.id] = self.make_move('Идти в центр')
            print(self.game.current_tick, 'Иди в центр')
        elif find_distance(self.my_unit.position, self.game.zone.current_center) > self.game.zone.current_radius:
            orders[self.my_unit.id] = self.make_move('Идти в центр')
            self.go_center = game.current_tick + 100
            print(self.game.current_tick, 'Иди в центр')
            
        elif self.enemy_dist > 20 and self.my_unit.weapon==0:

            if self.closest_gun is None:
                orders[self.my_unit.id] = self.make_move('Идти в центр')
            else:
                orders[self.my_unit.id] = self.make_move('Оружие')
                    
        elif self.my_unit.ammo[self.my_unit.weapon] == 0:
            print(game.current_tick, 'ammo', self.my_unit.ammo[self.my_unit.weapon], self.current_weapon.max_inventory_ammo)
            
            if self.closest_ammo is None:
                orders[self.my_unit.id] = self.make_move('Идти в центр')
            else:
                orders[self.my_unit.id] = self.make_move('Патроны')

        elif len(enemies) > 0:
            print(self.game.current_tick, 'len enemies > 0')
            
            if self.enemy_dist < self.current_weapon.projectile_life_time * self.current_weapon.projectile_speed:
                action = 'aim_true'
                print(game.current_tick, 'aim_true')
            elif self.enemy_dist < self.current_weapon.projectile_life_time * self.current_weapon.projectile_speed*1.05:
                action = 'aim_false'
                print(game.current_tick, 'aim_false')
            
            elif back_sounds_dist < self.current_weapon.projectile_life_time * self.current_weapon.projectile_speed * 0.6:
                orders[self.my_unit.id] = self.make_order(
                    Vec2(self.closest_back.x-self.my_unit.position.x, self.closest_back.y-self.my_unit.position.y),
                    Vec2(self.closest_back.x-self.my_unit.position.x, self.closest_back.y-self.my_unit.position.y),
                    action=None
                )
                print(game.current_tick, 'back')
                return Order(orders)
            else:
                action = self.add_action
                
            move_x = self.closest_enemy.position.x-self.my_unit.position.x
            move_y = self.closest_enemy.position.y-self.my_unit.position.y
            
            dist_to_enemy = find_distance(self.closest_enemy.position, self.my_unit.position)
            projectile_time = dist_to_enemy/self.current_weapon.projectile_speed
            new_dist_to_enemy = find_distance(
                            Vec2(self.closest_enemy.position.x+self.closest_enemy.velocity.x*projectile_time,
                                 self.closest_enemy.position.y+self.closest_enemy.velocity.y*projectile_time),
                            self.my_unit.position)
            projectile_time = ((dist_to_enemy+new_dist_to_enemy) / 2 - self.game_constants.unit_radius*2) / self.current_weapon.projectile_speed
                
            if self.need_health:
                orders[self.my_unit.id] = self.make_order(
                    Vec2(-move_x, -move_y),
                    Vec2(move_x+self.closest_enemy.velocity.x*projectile_time,
                        move_y+self.closest_enemy.velocity.y*projectile_time),
                    action=action
                )
            else:
                orders[self.my_unit.id] = self.make_order(
                    Vec2(move_x, move_y),
                    Vec2(move_x+self.closest_enemy.velocity.x*projectile_time,
                        move_y+self.closest_enemy.velocity.y*projectile_time),
                    action=action
                )
                
        elif back_sounds_dist < self.current_weapon.projectile_life_time * self.current_weapon.projectile_speed:
            orders[self.my_unit.id] = self.make_order(
                    Vec2(self.closest_back.x-self.my_unit.position.x, self.closest_back.y-self.my_unit.position.y),
                    Vec2(self.closest_back.x-self.my_unit.position.x, self.closest_back.y-self.my_unit.position.y),
                    action=None
                )
            print('new_back', self.closest_back.x, self.my_unit.position.x, self.closest_back.y, self.my_unit.position.y)
            
        elif back_sounds_dist < self.game_constants.view_distance:
            orders[self.my_unit.id] = self.make_order(
                    Vec2(self.closest_back.x-self.my_unit.position.x, self.closest_back.y-self.my_unit.position.y),
                    Vec2(self.closest_back.x-self.my_unit.position.x, self.closest_back.y-self.my_unit.position.y),
                    action=None
                )
            print('NEWNENWENWENW back')
            
        elif self.need_shield:
            print(game.current_tick, 'shield', self.shield_dist, self.closest_shield)
            if self.closest_shield is None:
                orders[self.my_unit.id] = self.make_move('Идти в центр')
            else:
                orders[self.my_unit.id] = self.make_move('Щит')
        
        elif self.need_ammo and self.need_shield:
            if self.ammo_dist < self.shield_dist:
                self.current_mission = 'ammo_add'
                orders[self.my_unit.id] = self.make_move('Патроны')
            else:
                self.current_mission = 'shield_add'
                orders[self.my_unit.id] = self.make_move('Щит')
        elif self.need_shield:
            orders[self.my_unit.id] = self.make_move('Щит')
        elif self.need_ammo:
            orders[self.my_unit.id] = self.make_move('Патроны')
        else:
            orders[self.my_unit.id] = self.make_move('Идти в центр')

        return Order(orders)
    
    
    def make_order(self, position: Vec2, direction: Vec2, action: str, pickup_id=None):
        
        if self.my_unit.action is None and (self.my_unit.aim == 0 or action in ['aim_false', 'aim_true']):
            if action == 'pickup':
                new_action = ActionOrder.Pickup(pickup_id)
                self.pickup_ids.append(pickup_id)
            elif action == 'shield_potion':
                new_action = ActionOrder.UseShieldPotion()
                self.busy = self.game.current_tick + self.game_constants.shield_potion_use_time
            elif action == 'aim_true':
                new_action = ActionOrder.Aim(True)
            elif action == 'aim_false':
                new_action = ActionOrder.Aim(False)
            else:
                new_action = None
        else:
            new_action = None
        return UnitOrder(position, direction, action=new_action)

    def debug_update(self, debug_interface: DebugInterface):
        pass

    def finish(self):
        pass
