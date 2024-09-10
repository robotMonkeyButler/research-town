import os
from collections import defaultdict
from typing import Any, Callable, Dict, List, Tuple

from ..configs import Config
from ..dbs import LogDB, PaperDB, ProgressDB, Proposal, Researcher, ResearcherDB
from ..envs.env_base import BaseEnv


class BaseEngine:
    def __init__(
        self,
        project_name: str,
        agent_db: ResearcherDB,
        paper_db: PaperDB,
        progress_db: ProgressDB,
        env_db: LogDB,
        config: Config,
        time_step: int = 0,
        stop_flag: bool = False,
    ) -> None:
        self.project_name = project_name
        self.agent_db = agent_db
        self.paper_db = paper_db
        self.progress_db = progress_db
        self.env_db = env_db
        self.config = config
        self.time_step = time_step
        self.stop_flag = stop_flag
        self.model_name = self.config.param.base_llm
        self.envs: Dict[str, BaseEnv] = {}
        self.transition_funcs: Dict[Tuple[str, str], Callable[..., Any]] = {}
        self.transitions: Dict[str, Dict[bool, str]] = defaultdict(dict)
        self.set_dbs()
        self.set_envs()
        self.set_transitions()
        self.set_transition_funcs()

    def set_dbs(self) -> None:
        self.agent_db.reset_role_avaialbility()
        self.env_db.set_project_name(self.project_name)
        self.progress_db.set_project_name(self.project_name)

    def set_envs(self) -> None:
        pass

    def set_transitions(self) -> None:
        pass

    def set_transition_funcs(self) -> None:
        pass

    def add_env(self, name: str, env: BaseEnv) -> None:
        self.envs[name] = env

    def add_transition_func(
        self, from_env: str, func: Callable[..., Any], to_env: str
    ) -> None:
        self.transition_funcs[(from_env, to_env)] = func

    def add_transition(self, from_env: str, pass_or_fail: bool, to_env: str) -> None:
        self.transitions[from_env][pass_or_fail] = to_env

    def start(self, task: str, env_name: str = 'start') -> None:
        if env_name not in self.envs:
            raise ValueError(f'env {env_name} not found')

        self.curr_env_name = env_name
        self.curr_env = self.envs[env_name]
        leader = self.find_agents(condition={}, query=task, num=1, update_fields={})[0]
        self.curr_env.on_enter(
            time_step=self.time_step,
            stop_flag=self.stop_flag,
            agent_profiles=[leader],
            agent_roles=['leader'],
            agent_models=[self.model_name],
        )

    def transition(self) -> None:
        pass_or_fail = self.curr_env.on_exit()
        next_env_name = self.transitions[self.curr_env_name][pass_or_fail]
        if (self.curr_env_name, next_env_name) in self.transition_funcs:
            input_data = self.transition_funcs[(self.curr_env_name, next_env_name)](
                self.curr_env
            )
        else:
            raise ValueError(
                f'no transition function from {self.curr_env_name} to {next_env_name}'
            )

        self.curr_env_name = next_env_name
        self.curr_env = self.envs[self.curr_env_name]
        self.curr_env.on_enter(
            time_step=self.time_step,
            stop_flag=self.stop_flag,
            **input_data,
        )

    def find_agents(
        self,
        condition: Dict[str, Any],
        query: str,
        num: int,
        update_fields: Dict[str, bool],
    ) -> List[Researcher]:
        candidates = self.agent_db.get(**condition)
        selected_agents = self.agent_db.match(
            query=query, agent_profiles=candidates, num=num
        )

        for agent in selected_agents:
            for field, value in update_fields.items():
                setattr(agent, field, value)
            self.agent_db.update(pk=agent.pk, updates=agent.model_dump())

        return selected_agents

    def set_leader(self, leader: Researcher) -> Researcher:
        return self.find_agents(
            condition={'pk': leader.pk},
            query=leader.bio,
            num=1,
            update_fields={
                'is_leader_candidate': True,
                'is_member_candidate': False,
                'is_reviewer_candidate': False,
                'is_chair_candidate': False,
            },
        )[0]

    def find_members(self, leader: Researcher, member_num: int) -> List[Researcher]:
        return self.find_agents(
            condition={'is_member_candidate': True},
            query=leader.bio,
            num=member_num,
            update_fields={
                'is_leader_candidate': False,
                'is_member_candidate': True,
                'is_reviewer_candidate': False,
                'is_chair_candidate': False,
            },
        )

    def find_reviewers(
        self, paper_submission: Proposal, reviewer_num: int
    ) -> List[Researcher]:
        return self.find_agents(
            condition={'is_reviewer_candidate': True},
            query=paper_submission.abstract,
            num=reviewer_num,
            update_fields={
                'is_leader_candidate': False,
                'is_member_candidate': False,
                'is_reviewer_candidate': True,
                'is_chair_candidate': False,
            },
        )

    def find_chair(self, paper_submission: Proposal) -> Researcher:
        return self.find_agents(
            condition={'is_chair_candidate': True},
            query=paper_submission.abstract,
            num=1,
            update_fields={
                'is_leader_candidate': False,
                'is_member_candidate': False,
                'is_reviewer_candidate': False,
                'is_chair_candidate': True,
            },
        )[0]

    def run(self, task: str) -> None:
        self.start(task=task)
        while self.curr_env_name != 'end':
            self.curr_env.run()
            self.time_step += 1
            self.transition()

    def save(self, save_file_path: str, with_embed: bool = False) -> None:
        if not os.path.exists(save_file_path):
            os.makedirs(save_file_path)

        self.agent_db.save_to_json(save_file_path, with_embed=with_embed)
        self.paper_db.save_to_json(save_file_path, with_embed=with_embed)
        self.progress_db.save_to_json(save_file_path)
        self.env_db.save_to_json(save_file_path)

    def load(self) -> None:
        pass
