#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
"""

__time__ = '2019/1/31 10:24'

import copy
import json
import os
import random
import re
import logging

from tatk.policy.policy import Policy
from tatk.task.multiwoz.goal_generator import GoalGenerator
from tatk.util.multiwoz.multiwoz_slot_trans import REF_USR_DA, REF_SYS_DA

DEF_VAL_UNK = '?'  # Unknown
DEF_VAL_DNC = 'don\'t care'  # Do not care
DEF_VAL_NUL = 'none'  # for none
DEF_VAL_BOOKED = 'yes'  # for booked
DEF_VAL_NOBOOK = 'no'  # for booked
NOT_SURE_VALS = [DEF_VAL_UNK, DEF_VAL_DNC, DEF_VAL_NUL, DEF_VAL_NOBOOK]

# import reflect table
REF_USR_DA_M = copy.deepcopy(REF_USR_DA)
REF_SYS_DA_M = {}
for dom, ref_slots in REF_SYS_DA.items():
    dom = dom.lower()
    REF_SYS_DA_M[dom] = {}
    for slot_a, slot_b in ref_slots.items():
        REF_SYS_DA_M[dom][slot_a.lower()] = slot_b
    REF_SYS_DA_M[dom]['none'] = None

# def book slot
BOOK_SLOT = ['people', 'day', 'stay', 'time']

class UserPolicyAgendaMultiWoz(Policy):
    """ The rule-based user policy model by agenda. Derived from the UserPolicy class """

    # load stand value
    with open(os.path.join(os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                'data/multiwoz/value_set.json')) as f:
        stand_value_dict = json.load(f)

    def __init__(self, max_goal_num=100, seed=2019):
        """
        Constructor for User_Policy_Agenda class.
        """
        self.max_turn = 40
        self.max_initiative = 4

        self.goal_generator = GoalGenerator(corpus_path=os.path.join(os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                'data/multiwoz/annotated_user_da_with_span_full.json'))

        self.__turn = 0
        self.goal = None
        self.agenda = None

        random.seed(seed)
        self.goal_seeds = [random.randint(1,1e7) for i in range(max_goal_num)]

        Policy.__init__(self)

    def init_session(self):
        """ Build new Goal and Agenda for next session """
        self.__turn = 0
        if len(self.goal_seeds)>1:
            self.goal = Goal(self.goal_generator, self.goal_seeds[0])
            self.goal_seeds = self.goal_seeds[1:]
        else:
            self.goal = Goal(self.goal_generator)
        self.domain_goals = self.goal.domain_goals
        self.agenda = Agenda(self.goal)

    def predict(self, state, sys_action):
        """
        Predict an user act based on state and preorder system action.
        Args:
            state (tuple): Dialog state.
            sys_action (tuple): Preorder system action.s
        Returns:
            action (tuple): User act.
            session_over (boolean): True to terminate session, otherwise session continues.
            reward (float): Reward given by user.
        """
        self.__turn += 2

        # At the beginning of a dialog when there is no NLU.
        if sys_action == "null":
            sys_action = {}

        if self.__turn > self.max_turn:
            self.agenda.close_session()
        else:
            sys_action = self._transform_sysact_in(sys_action)
            self.agenda.update(sys_action, self.goal)
            if self.goal.task_complete():
                self.agenda.close_session()

        # A -> A' + user_action
        # action = self.agenda.get_action(random.randint(1, self.max_initiative))
        action = self.agenda.get_action(self.max_initiative)

        # Is there any action to say?
        session_over = self.agenda.is_empty()

        # reward
        reward = self._reward()

        # transform to DA
        action = self._transform_usract_out(action)

        return action, session_over, reward

    def _reward(self):
        """
        Calculate reward based on task completion
        Returns:
            reward (float): Reward given by user.
        """
        if self.goal.task_complete():
            reward = 2.0 * self.max_turn
        elif self.agenda.is_empty():
            reward = -1.0 * self.max_turn
        else:
            reward = -1.0
        return reward

    @classmethod
    def _transform_usract_out(cls, action):
        new_action = {}
        for act in action.keys():
            if '-' in act:
                if 'general' not in act:
                    (dom, intent) = act.split('-')
                    new_act = dom.capitalize() + '-' + intent.capitalize()
                    new_action[new_act] = []
                    for pairs in action[act]:
                        slot = REF_USR_DA_M[dom.capitalize()].get(pairs[0], None)
                        if slot is not None:
                            new_action[new_act].append([slot, pairs[1]])
                    #new_action[new_act] = [[REF_USR_DA_M[dom.capitalize()].get(pairs[0], pairs[0]), pairs[1]] for pairs in action[act]]
                else:
                    new_action[act] = action[act]
            else:
                pass
        return new_action

    @classmethod
    def _transform_sysact_in(cls, action):
        new_action = {}
        if not isinstance(action, dict):
            logging.warning(f'illegal da: {action}')
            return new_action

        for act in action.keys():
            if not isinstance(act, str) or '-' not in act:
                logging.warning(f'illegal act: {act}')
                continue

            if 'general' not in act:
                (dom, intent) = act.lower().split('-')
                if dom in REF_SYS_DA_M.keys():
                    new_list = []
                    for pairs in action[act]:
                        if (not isinstance(pairs, list) and not isinstance(pairs, tuple)) or\
                                (len(pairs) < 2) or\
                                (not isinstance(pairs[0], str) or (not isinstance(pairs[1], str) and not isinstance(pairs[1], int))):
                            logging.warning(f'illegal pairs: {pairs}')
                            continue

                        if REF_SYS_DA_M[dom].get(pairs[0].lower(), None) is not None:
                            new_list.append([REF_SYS_DA_M[dom][pairs[0].lower()], cls._normalize_value(dom, intent, REF_SYS_DA_M[dom][pairs[0].lower()], pairs[1])])

                    if len(new_list) > 0:
                        new_action[act.lower()] = new_list
            else:
                new_action[act.lower()] = action[act]

        return new_action

    @classmethod
    def _normalize_value(cls, domain, intent, slot, value):
        if intent == 'request':
            return DEF_VAL_UNK

        if domain not in cls.stand_value_dict.keys():
            return value

        if slot not in cls.stand_value_dict[domain]:
            return value

        value_list = cls.stand_value_dict[domain][slot]
        low_value_list = [item.lower() for item in value_list]
        value_list = list(set(value_list).union(set(low_value_list)))
        if value not in value_list:
            normalized_v = simple_fuzzy_match(value_list, value)
            if normalized_v is not None:
                return normalized_v
            # try some transformations
            cand_values = transform_value(value)
            for cv in cand_values:
                _nv = simple_fuzzy_match(value_list, cv)
                if _nv is not None:
                    return _nv
            if check_if_time(value):
                return value

            logging.debug('Value not found in standard value set: [%s] (slot: %s domain: %s)' % (value, slot, domain))
        return value

def transform_value(value):
    cand_list = []
    # a 's -> a's
    if " 's" in value:
        cand_list.append(value.replace(" 's", "'s"))
    # a - b -> a-b
    if " - " in value:
        cand_list.append(value.replace(" - ", "-"))
    return cand_list

def simple_fuzzy_match(value_list, value):
    # check contain relation
    v0 = ' '.join(value.split())
    v0N = ''.join(value.split())
    for val in value_list:
        v1 = ' '.join(val.split())
        if v0 in v1 or v1 in v0 or v0N in v1 or v1 in v0N:
            return v1
    value = value.lower()
    v0 = ' '.join(value.split())
    v0N = ''.join(value.split())
    for val in value_list:
        v1 = ' '.join(val.split())
        if v0 in v1 or v1 in v0 or v0N in v1 or v1 in v0N:
            return v1
    return None

def check_if_time(value):
    value = value.strip()
    match = re.search(r"(\d{1,2}:\d{1,2})", value)
    if match is None:
        return False
    groups = match.groups()
    if len(groups) <= 0:
        return False
    return True


class Goal(object):
    """ User Goal Model Class. """

    def __init__(self, goal_generator: GoalGenerator, seed=None):
        """
        create new Goal by random
        Args:
            goal_generator (GoalGenerator): Goal Gernerator.
        """
        self.domain_goals = goal_generator.get_user_goal(seed)

        self.domains = list(self.domain_goals['domain_ordering'])
        del self.domain_goals['domain_ordering']

        for domain in self.domains:
            if 'reqt' in self.domain_goals[domain].keys():
                self.domain_goals[domain]['reqt'] = {slot: DEF_VAL_UNK for slot in self.domain_goals[domain]['reqt']}

            if 'book' in self.domain_goals[domain].keys():
                self.domain_goals[domain]['booked'] = DEF_VAL_UNK

    def task_complete(self):
        """
        Check that all requests have been met
        Returns:
            (boolean): True to accomplish.
        """
        for domain in self.domains:
            if 'reqt' in self.domain_goals[domain]:
                reqt_vals = self.domain_goals[domain]['reqt'].values()
                for val in reqt_vals:
                    if val in NOT_SURE_VALS:
                        return False

            if 'booked' in self.domain_goals[domain]:
                if self.domain_goals[domain]['booked'] in NOT_SURE_VALS:
                    return False
        return True

    def next_domain_incomplete(self):
        # request
        for domain in self.domains:
            # reqt
            if 'reqt' in self.domain_goals[domain]:
                requests = self.domain_goals[domain]['reqt']
                unknow_reqts = [key for (key, val) in requests.items() if val in NOT_SURE_VALS]
                if len(unknow_reqts) > 0:
                    return domain, 'reqt', ['name'] if 'name' in unknow_reqts else unknow_reqts

            # book
            if 'booked' in self.domain_goals[domain]:
                if self.domain_goals[domain]['booked'] in NOT_SURE_VALS:
                    return domain, 'book', \
                           self.domain_goals[domain]['fail_book'] if 'fail_book' in self.domain_goals[domain].keys() else self.domain_goals[domain]['book']

        return None, None, None

    def __str__(self):
        return '-----Goal-----\n' + \
               json.dumps(self.domain_goals, indent=4) + \
               '\n-----Goal-----'


class Agenda(object):
    def __init__(self, goal: Goal):
        """
        Build a new agenda from goal
        Args:
            goal (Goal): User goal.
        """

        def random_sample(data, minimum=0, maximum=1000):
            return random.sample(data, random.randint(min(len(data), minimum), min(len(data), maximum)))

        self.CLOSE_ACT = 'general-bye'
        self.HELLO_ACT = 'general-greet'
        self.__cur_push_num = 0

        self.__stack = []

        # there is a 'bye' action at the bottom of the stack
        self.__push(self.CLOSE_ACT)

        for idx in range(len(goal.domains) - 1, -1, -1):
            domain = goal.domains[idx]

            # inform
            if 'fail_info' in goal.domain_goals[domain]:
                for slot in random_sample(goal.domain_goals[domain]['fail_info'].keys(),
                                          len(goal.domain_goals[domain]['fail_info'])):
                    self.__push(domain + '-inform', slot, goal.domain_goals[domain]['fail_info'][slot])
            elif 'info' in goal.domain_goals[domain]:
                for slot in random_sample(goal.domain_goals[domain]['info'].keys(),
                                          len(goal.domain_goals[domain]['info'])):
                    self.__push(domain + '-inform', slot, goal.domain_goals[domain]['info'][slot])

        self.cur_domain = None

    def update(self, sys_action, goal: Goal):
        """
        update Goal by current agent action and current goal. { A' + G" + sys_action -> A" }
        Args:
            sys_action (tuple): Preorder system action.s
            goal (Goal): User Goal
        """
        self.__cur_push_num = 0
        self._update_current_domain(sys_action, goal)

        for diaact in sys_action.keys():
            slot_vals = sys_action[diaact]
            if 'nooffer' in diaact:
                if self.update_domain(diaact, slot_vals, goal):
                    return
            elif 'nobook' in diaact:
                if self.update_booking(diaact, slot_vals, goal):
                    return

        for diaact in sys_action.keys():
            if 'nooffer' in diaact or 'nobook' in diaact:
                continue

            slot_vals = sys_action[diaact]
            if 'booking' in diaact:
                if self.update_booking(diaact, slot_vals, goal):
                    return
            elif 'general' in diaact:
                if self.update_general(diaact, slot_vals, goal):
                    return
            else:
                if self.update_domain(diaact, slot_vals, goal):
                    return

        unk_dom, unk_type, data = goal.next_domain_incomplete()
        if unk_dom is not None:
            if unk_type == 'reqt' and not self._check_reqt_info(unk_dom) and not self._check_reqt(unk_dom):
                for slot in data:
                    self._push_item(unk_dom + '-request', slot, DEF_VAL_UNK)
            elif unk_type == 'book' and not self._check_reqt_info(unk_dom) and not self._check_book_info(unk_dom):
                for (slot, val) in data.items():
                    self._push_item(unk_dom + '-inform', slot, val)

    def update_booking(self, diaact, slot_vals, goal: Goal):
        """
        Handel Book-XXX
        :param diaact:      Dial-Act
        :param slot_vals:   slot value pairs
        :param goal:        Goal
        :return:            True:user want to close the session. False:session is continue
        """
        _, intent = diaact.split('-')
        domain = self.cur_domain

        if domain not in goal.domains:
            return False

        g_reqt = goal.domain_goals[domain].get('reqt', dict({}))
        g_info = goal.domain_goals[domain].get('info', dict({}))
        g_fail_info = goal.domain_goals[domain].get('fail_info', dict({}))
        g_book = goal.domain_goals[domain].get('book', dict({}))
        g_fail_book = goal.domain_goals[domain].get('fail_book', dict({}))

        if intent in ['book', 'inform']:
            info_right = True
            for [slot, value] in slot_vals:
                if slot == 'time':
                    if domain in ['train', 'restaurant']:
                        slot = 'duration' if domain == 'train' else 'time'
                    else:
                        logging.warning(f'illegal booking slot: {slot}, domain: {domain}')
                        continue

                if slot in g_reqt:
                    if not self._check_reqt_info(domain):
                        self._remove_item(domain + '-request', slot)
                        if value in NOT_SURE_VALS:
                            g_reqt[slot] = '\"' + value + '\"'
                        else:
                            g_reqt[slot] = value

                elif slot in g_fail_info and value != g_fail_info[slot]:
                    self._push_item(domain + '-inform', slot, g_fail_info[slot])
                    info_right = False
                elif len(g_fail_info) <= 0 and slot in g_info and value != g_info[slot]:
                    self._push_item(domain + '-inform', slot, g_info[slot])
                    info_right = False

                elif slot in g_fail_book and value != g_fail_book[slot]:
                    self._push_item(domain + '-inform', slot, g_fail_book[slot])
                    info_right = False
                elif len(g_fail_book) <= 0 and slot in g_book and value != g_book[slot]:
                    self._push_item(domain + '-inform', slot, g_book[slot])
                    info_right = False

                else:
                    pass

            if intent == 'book' and info_right:
                # booked ok
                if 'booked' in goal.domain_goals[domain]:
                    goal.domain_goals[domain]['booked'] = DEF_VAL_BOOKED
                self._push_item('general-thank')

        elif intent in ['nobook']:
            if len(g_fail_book) > 0:
                # Discard fail_book data and update the book data to the stack
                for slot in g_book.keys():
                    if (slot not in g_fail_book) or (slot in g_fail_book and g_fail_book[slot] != g_book[slot]):
                        self._push_item(domain + '-inform', slot, g_book[slot])

                # change fail_info name
                goal.domain_goals[domain]['fail_book_fail'] = goal.domain_goals[domain].pop('fail_book')
            elif 'booked' in goal.domain_goals[domain].keys():
                self.close_session()
                return True

        elif intent in ['request']:
            for [slot, _] in slot_vals:
                if slot == 'time':
                    if domain in ['train', 'restaurant']:
                        slot = 'duration' if domain == 'train' else 'time'
                    else:
                        logging.warning('illegal booking slot: %s, slot: %s domain' % (slot, domain))
                        continue

                if slot in g_reqt:
                    pass
                elif slot in g_fail_info:
                    self._push_item(domain + '-inform', slot, g_fail_info[slot])
                elif len(g_fail_info) <= 0 and slot in g_info:
                    self._push_item(domain + '-inform', slot, g_info[slot])

                elif slot in g_fail_book:
                    self._push_item(domain + '-inform', slot, g_fail_book[slot])
                elif len(g_fail_book) <= 0 and slot in g_book:
                    self._push_item(domain + '-inform', slot, g_book[slot])

                else:

                    if domain == 'taxi' and (slot == 'destination' or slot == 'departure'):
                        places = [dom for dom in goal.domains[: goal.domains.index('taxi')] if
                                  'address' in goal.domain_goals[dom]['reqt']]

                        if len(places) >= 1 and slot == 'destination' and \
                                goal.domain_goals[places[-1]]['reqt']['address'] not in NOT_SURE_VALS:
                            self._push_item(domain + '-inform', slot, goal.domain_goals[places[-1]]['reqt']['address'])

                        elif len(places) >= 2 and slot == 'departure' and \
                                goal.domain_goals[places[-2]]['reqt']['address'] not in NOT_SURE_VALS:
                            self._push_item(domain + '-inform', slot, goal.domain_goals[places[-2]]['reqt']['address'])

                        elif random.random() < 0.5:
                            self._push_item(domain + '-inform', slot, DEF_VAL_DNC)

                    elif random.random() < 0.5:
                        self._push_item(domain + '-inform', slot, DEF_VAL_DNC)

        return False

    def update_domain(self, diaact, slot_vals, goal: Goal):
        """
        Handel Domain-XXX
        :param diaact:      Dial-Act
        :param slot_vals:   slot value pairs
        :param goal:        Goal
        :return:            True:user want to close the session. False:session is continue
        """
        domain, intent = diaact.split('-')

        if domain not in goal.domains:
            return False

        g_reqt = goal.domain_goals[domain].get('reqt', dict({}))
        g_info = goal.domain_goals[domain].get('info', dict({}))
        g_fail_info = goal.domain_goals[domain].get('fail_info', dict({}))
        g_book = goal.domain_goals[domain].get('book', dict({}))
        g_fail_book = goal.domain_goals[domain].get('fail_book', dict({}))

        if intent in ['inform', 'recommend', 'offerbook', 'offerbooked']:
            info_right = True
            for [slot, value] in slot_vals:
                if slot in g_reqt:
                    if not self._check_reqt_info(domain):
                        self._remove_item(domain + '-request', slot)
                        if value in NOT_SURE_VALS:
                            g_reqt[slot] = '\"' + value + '\"'
                        else:
                            g_reqt[slot] = value

                elif slot in g_fail_info and value != g_fail_info[slot]:
                    self._push_item(domain + '-inform', slot, g_fail_info[slot])
                    info_right = False
                elif len(g_fail_info) <= 0 and slot in g_info and value != g_info[slot]:
                    self._push_item(domain + '-inform', slot, g_info[slot])
                    info_right = False

                elif slot in g_fail_book and value != g_fail_book[slot]:
                    self._push_item(domain + '-inform', slot, g_fail_book[slot])
                    info_right = False
                elif len(g_fail_book) <= 0 and slot in g_book and value != g_book[slot]:
                    self._push_item(domain + '-inform', slot, g_book[slot])
                    info_right = False

                else:
                    pass

            if intent == 'offerbooked' and info_right:
                # booked ok
                if 'booked' in goal.domain_goals[domain]:
                    goal.domain_goals[domain]['booked'] = DEF_VAL_BOOKED
                self._push_item('general-thank')

        elif intent in ['request']:
            for [slot, _] in slot_vals:
                if slot in g_reqt:
                    pass
                elif slot in g_fail_info:
                    self._push_item(domain + '-inform', slot, g_fail_info[slot])
                elif len(g_fail_info) <= 0 and slot in g_info:
                    self._push_item(domain + '-inform', slot, g_info[slot])

                elif slot in g_fail_book:
                    self._push_item(domain + '-inform', slot, g_fail_book[slot])
                elif len(g_fail_book) <= 0 and slot in g_book:
                    self._push_item(domain + '-inform', slot, g_book[slot])

                else:

                    if domain == 'taxi' and (slot == 'destination' or slot == 'departure'):
                        places = [dom for dom in goal.domains[: goal.domains.index('taxi')] if
                                  'address' in goal.domain_goals[dom]['reqt']]

                        if len(places) >= 1 and slot == 'destination' and \
                                goal.domain_goals[places[-1]]['reqt']['address'] not in NOT_SURE_VALS:
                            self._push_item(domain + '-inform', slot, goal.domain_goals[places[-1]]['reqt']['address'])

                        elif len(places) >= 2 and slot == 'departure' and \
                                goal.domain_goals[places[-2]]['reqt']['address'] not in NOT_SURE_VALS:
                            self._push_item(domain + '-inform', slot, goal.domain_goals[places[-2]]['reqt']['address'])

                        elif random.random() < 0.5:
                            self._push_item(domain + '-inform', slot, DEF_VAL_DNC)

                    elif random.random() < 0.5:
                        self._push_item(domain + '-inform', slot, DEF_VAL_DNC)

        elif intent in ['nooffer']:
            if len(g_fail_info) > 0:
                # update info data to the stack
                for slot in g_info.keys():
                    if (slot not in g_fail_info) or (slot in g_fail_info and g_fail_info[slot] != g_info[slot]):
                        self._push_item(domain + '-inform', slot, g_info[slot])

                # change fail_info name
                goal.domain_goals[domain]['fail_info_fail'] = goal.domain_goals[domain].pop('fail_info')
            elif len(g_reqt.keys()) > 0:
                self.close_session()
                return True

        elif intent in ['select']:
            # delete Choice
            slot_vals = [[slot, val] for [slot, val] in slot_vals if slot != 'choice']

            if len(slot_vals) > 0:
                slot = slot_vals[0][0]

                if slot in g_fail_info:
                    self._push_item(domain + '-inform', slot, g_fail_info[slot])
                elif len(g_fail_info) <= 0 and slot in g_info:
                    self._push_item(domain + '-inform', slot, g_info[slot])

                elif slot in g_fail_book:
                    self._push_item(domain + '-inform', slot, g_fail_book[slot])
                elif len(g_fail_book) <= 0 and slot in g_book:
                    self._push_item(domain + '-inform', slot, g_book[slot])

                else:
                    if not self._check_reqt_info(domain):
                        [slot, value] = random.choice(slot_vals)
                        self._push_item(domain + '-inform', slot, value)

                        if slot in g_reqt:
                            self._remove_item(domain + '-request', slot)
                            g_reqt[slot] = value

        return False

    def update_general(self, diaact, slot_vals, goal: Goal):
        domain, intent = diaact.split('-')

        if intent == 'bye':
            # self.close_session()
            # return True
            pass
        elif intent == 'greet':
            pass
        elif intent == 'reqmore':
            pass
        elif intent == 'welcome':
            pass

        return False

    def close_session(self):
        """ Clear up all actions """
        self.__stack = []
        self.__push(self.CLOSE_ACT)

    def get_action(self, initiative=1):
        """
        get multiple acts based on initiative
        Args:
            initiative (int): number of slots , just for 'inform'
        Returns:
            action (dict): user diaact
        """
        diaacts, slots, values = self.__pop(initiative)
        action = {}
        for (diaact, slot, value) in zip(diaacts, slots, values):
            if diaact not in action.keys():
                action[diaact] = []
            action[diaact].append([slot, value])

        return action

    def is_empty(self):
        """
        Is the agenda already empty
        Returns:
            (boolean): True for empty, False for not.
        """
        return len(self.__stack) <= 0

    def _update_current_domain(self, sys_action, goal: Goal):
        for diaact in sys_action.keys():
            domain, _ = diaact.split('-')
            if domain in goal.domains:
                self.cur_domain = domain

    def _remove_item(self, diaact, slot=DEF_VAL_UNK):
        for idx in range(len(self.__stack)):
            if 'general' in diaact:
                if self.__stack[idx]['diaact'] == diaact:
                    self.__stack.remove(self.__stack[idx])
                    break
            else:
                if self.__stack[idx]['diaact'] == diaact and self.__stack[idx]['slot'] == slot:
                    self.__stack.remove(self.__stack[idx])
                    break

    def _push_item(self, diaact, slot=DEF_VAL_NUL, value=DEF_VAL_NUL):
        self._remove_item(diaact, slot)
        self.__push(diaact, slot, value)
        self.__cur_push_num += 1

    def _check_item(self, diaact, slot=None):
        for idx in range(len(self.__stack)):
            if slot is None:
                if self.__stack[idx]['diaact'] == diaact:
                    return True
            else:
                if self.__stack[idx]['diaact'] == diaact and self.__stack[idx]['slot'] == slot:
                    return True
        return False

    def _check_reqt(self, domain):
        for idx in range(len(self.__stack)):
            if self.__stack[idx]['diaact'] == domain + '-request':
                return True
        return False

    def _check_reqt_info(self, domain):
        for idx in range(len(self.__stack)):
            if self.__stack[idx]['diaact'] == domain + '-inform' and self.__stack[idx]['slot'] not in BOOK_SLOT:
                return True
        return False

    def _check_book_info(self, domain):
        for idx in range(len(self.__stack)):
            if self.__stack[idx]['diaact'] == domain + '-inform' and self.__stack[idx]['slot'] in BOOK_SLOT:
                return True
        return False

    def __check_next_diaact_slot(self):
        if len(self.__stack) > 0:
            return self.__stack[-1]['diaact'], self.__stack[-1]['slot']
        return None, None

    def __check_next_diaact(self):
        if len(self.__stack) > 0:
            return self.__stack[-1]['diaact']
        return None

    def __push(self, diaact, slot=DEF_VAL_NUL, value=DEF_VAL_NUL):
        self.__stack.append({'diaact': diaact, 'slot': slot, 'value': value})

    def __pop(self, initiative=1):
        diaacts = []
        slots = []
        values = []

        p_diaact, p_slot = self.__check_next_diaact_slot()
        if p_diaact.split('-')[1] == 'inform' and p_slot in BOOK_SLOT:
            for _ in range(10 if self.__cur_push_num == 0 else self.__cur_push_num):
                try:
                    item = self.__stack.pop(-1)
                    diaacts.append(item['diaact'])
                    slots.append(item['slot'])
                    values.append(item['value'])

                    cur_diaact = item['diaact']

                    next_diaact, next_slot = self.__check_next_diaact_slot()
                    if next_diaact is None or \
                            next_diaact != cur_diaact or \
                            next_diaact.split('-')[1] != 'inform' or next_slot not in BOOK_SLOT:
                        break
                except:
                    break
        else:
            for _ in range(initiative if self.__cur_push_num == 0 else self.__cur_push_num):
                try:
                    item = self.__stack.pop(-1)
                    diaacts.append(item['diaact'])
                    slots.append(item['slot'])
                    values.append(item['value'])

                    cur_diaact = item['diaact']

                    next_diaact = self.__check_next_diaact()
                    if next_diaact is None or \
                            next_diaact != cur_diaact or \
                            (cur_diaact.split('-')[1] == 'request' and item['slot'] == 'name'):
                        break
                except:
                    break

        return diaacts, slots, values

    def __str__(self):
        text = '\n-----agenda-----\n'
        text += '<stack top>\n'
        for item in reversed(self.__stack):
            text += str(item) + '\n'
        text += '<stack btm>\n'
        text += '-----agenda-----\n'
        return text


def test():
    user_simulator = UserPolicyAgendaMultiWoz()
    user_simulator.init_session()

    test_turn(user_simulator, {'Train-NoOffer': [['Day', 'saturday'], ['Dest', 'place'], ['Depart', 'place']]})
    test_turn(user_simulator, {'Hotel-NoOffer': [['stars', '3'], ['internet', 'yes'], ['type', 'guest house']], 'Hotel-Request': [['stars', '?']]})
    test_turn(user_simulator, {"Hotel-Inform": [["Type", "qqq"], ["Parking", "no"], ["Internet", "yes"]]})
    test_turn(user_simulator, {"Hotel-Inform": [["Type", "qqq"], ["Parking", "no"]]})
    test_turn(user_simulator, {"Booking-Request": [["Day", "123"], ["Time", "no"]]})
    test_turn(user_simulator, {"Hotel-Request": [["Addr", "?"]], "Hotel-Inform": [["Internet", "yes"]]})
    test_turn(user_simulator, {"Hotel-Request": [["Type", "?"], ["Parking", "?"]]})
    test_turn(user_simulator, {"Hotel-Nooffer": [["Stars", "3"]], "Hotel-Request": [["Parking", "?"]]})
    test_turn(user_simulator, {"Hotel-Select": [["Area", "aa"], ["Area", "bb"], ["Area", "cc"], ['Choice', 3]]})
    test_turn(user_simulator, {"Hotel-Offerbooked": [["Ref", "12345"]]})

def test_turn(user_simulator, sys_action):
    print('input:', sys_action)
    action, session_over, reward = user_simulator.predict(None, sys_action)
    print('----------------------------------')
    print('sys_action :' + str(sys_action))
    print('user_action:' + str(action))
    print('over       :' + str(session_over))
    print('reward     :' + str(reward))
    print(user_simulator.goal)
    print(user_simulator.agenda)


def test_with_system():
    from tatk.policy.multiwoz.rule_based_multiwoz_bot import RuleBasedMultiwozBot, fake_state
    user_simulator = UserPolicyAgendaMultiWoz()
    user_simulator.init_session()
    state = fake_state()
    system_agent = RuleBasedMultiwozBot()
    sys_action = system_agent.predict(state)
    action, session_over, reward = user_simulator.predict(None, sys_action)
    print("Sys:")
    print(json.dumps(sys_action, indent=4))
    print("User:")
    print(json.dumps(action, indent=4))

