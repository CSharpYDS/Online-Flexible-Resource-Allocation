"""
Implementation of a server with a fix amount of available resources at each time step
"""

from typing import List, Dict

from agents.resource_weighting_agent import ResourceWeightingAgent
from agents.task_pricing_agent import TaskPricingAgent
from core.task import Task, TaskStage


class Server(object):
    tasks: List[Task] = []

    storage_capacity: float = 0
    computational_capacity: float = 0
    bandwidth_capacity: float = 0

    pricing_agent: TaskPricingAgent = None
    resource_weighting_agent: ResourceWeightingAgent = None

    def __init__(self, storage_capacity: float, computational_capacity: float, bandwidth_capacity: float):
        self.name: str = "1"
        self.storage_capacity = storage_capacity
        self.computational_capacity = computational_capacity
        self.bandwidth_capacity = bandwidth_capacity

    def set_agents(self, pricing_agent, resource_weighting_agent):
        self.pricing_agent = pricing_agent
        self.resource_weighting_agent = resource_weighting_agent

    def price_task(self, task: Task) -> float:
        assert self.pricing_agent is not None

        return self.pricing_agent.price_task(task, self.tasks, self)

    def allocate_task(self, task, second_min_price):
        self.tasks.append(task)

        self.pricing_agent.task_allocated(task, second_min_price)

    def allocate_resources(self):
        loading_weights: Dict[Task, float] = {}
        compute_weights: Dict[Task, float] = {}
        sending_weights: Dict[Task, float] = {}

        # Stage 1: Finding the weighting for each of the tasks
        for task in self.tasks:
            weighting = self.resource_weighting_agent.weight_task(task)

            if task.stage == TaskStage.LOADING:
                loading_weights[task] = weighting
            elif task.stage == TaskStage.COMPUTING:
                compute_weights[task] = weighting
            elif task.stage == TaskStage.SENDING:
                sending_weights[task] = weighting

        available_storage: float = self.storage_capacity
        available_computation: float = self.computational_capacity
        available_bandwidth: float = self.bandwidth_capacity

        # Stage 2: Allocate the compute resources to tasks
        completed_compute_stage: bool = True
        while completed_compute_stage and compute_weights:
            compute_unit: float = available_computation / sum(compute_weights.values())
            completed_compute_stage = False

            for task, weight in compute_weights.items():
                if task.required_computation - task.compute_progress <= weight * compute_unit:
                    compute_resources: float = task.required_computation - task.compute_progress

                    task.allocate_compute_resources(compute_resources)

                    available_computation -= compute_resources
                    available_storage -= task.loading_progress

                    completed_compute_stage = True

                    compute_weights.pop(task)

        if compute_weights:
            compute_unit = available_computation / sum(compute_weights.values())
            for task, weight in compute_weights.items():
                task.allocate_compute_resources(compute_unit * weight)

        # Stage 3: Allocate the bandwidth resources to task
        completed_bandwidth_stage: bool = True
        while completed_bandwidth_stage and (loading_weights or sending_weights):
            bandwidth_unit: float = available_bandwidth / (
                        sum(loading_weights.values()) + sum(sending_weights.values()))
            completed_bandwidth_stage = False

            for task, weight in sending_weights.items():
                if task.required_results_data - task.sending_results_progress <= weight * bandwidth_unit:
                    sending_resources: float = task.required_results_data - task.sending_results_progress
                    task.allocate_sending_resources(sending_resources)

                    available_bandwidth -= sending_resources
                    available_storage -= task.loading_progress

                    completed_bandwidth_stage = True

                    sending_weights.pop(task)

            for task, weight in loading_weights.items():
                if task.required_storage - task.loading_progress <= weight * bandwidth_unit and \
                        task.loading_progress + min(task.required_storage - task.loading_progress,
                                                    weight * bandwidth_unit) <= available_storage:
                    loading_resources: float = task.required_storage - task.loading_progress
                    task.allocate_loading_resources(loading_resources)

                    available_bandwidth -= loading_resources
                    available_storage -= task.loading_progress

                    completed_bandwidth_stage = True

                    loading_weights.pop(task)

        if loading_weights or sending_weights:
            bandwidth_unit: float = available_bandwidth / (
                            sum(loading_weights.values()) + sum(sending_weights.values()))
            if loading_weights:
                for task, weight in loading_weights.items():
                    task.allocate_loading_resources(bandwidth_unit * weight)

            if sending_weights:
                for task, weight in sending_weights.items():
                    task.allocate_sending_resources(bandwidth_unit * weight)
