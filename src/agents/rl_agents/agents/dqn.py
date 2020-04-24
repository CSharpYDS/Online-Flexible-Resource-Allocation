"""
Implementation of Deep Q Network, Double DQN and Dueling DQN mechanisms for task pricing and resource allocation agents
"""

from __future__ import annotations

import os
from abc import ABC
from typing import List, Union, Dict
import random as rnd

import gin.tf
import tensorflow as tf

from agents.rl_agents.rl_agents import ReinforcementLearningAgent, ResourceWeightingRLAgent, TaskPricingRLAgent
from env.server import Server
from env.task import Task


@gin.configurable
class DqnAgent(ReinforcementLearningAgent, ABC):
    """
    Deep Q network Agent based on the paper by Deepmind
    Deep Q Network based on Playing Atari with Deep Reinforcement Learning
        (https://arxiv.org/abs/1312.5602)
    """

    def __init__(self, network: tf.keras.Model, optimiser: tf.keras.optimizers.Optimizer = tf.keras.optimizers.Adam(),
                 target_update_tau: float = 1.0, target_update_frequency: int = 2500,
                 initial_epsilon: float = 1, final_epsilon: float = 0.1, epsilon_steps: int = 10000,
                 epsilon_update_frequency: int = 100, **kwargs):
        """
        Constructor of the dqn agent
        Args:
            network: Agent model network that is used for the target network
            optimiser: Network optimiser
            target_update_tau: Target network update tau value
            target_update_frequency: Target network update frequency
            initial_epsilon: initial exploration factor
            final_epsilon: final exploration factor
            epsilon_steps: number of exploration steps
            epsilon_update_frequency: exploration factor update frequency
            **kwargs:
        """
        ReinforcementLearningAgent.__init__(self, **kwargs)

        # Set the model and target Q networks
        self.model_network = network
        self.target_network: tf.keras.Model = tf.keras.models.clone_model(network)
        self.num_actions: int = network.output_shape[1]

        self.optimiser = optimiser

        # Target update frequency and tau
        self.target_update_frequency = target_update_frequency
        self.target_update_tau = target_update_tau

        # Exploration attributes: initial, final, total steps, epsilon itself and the update frequency
        self.initial_epsilon = initial_epsilon
        self.final_epsilon = final_epsilon
        self.grad_epsilon: float = (final_epsilon - initial_epsilon) * epsilon_steps
        self.epsilon = initial_epsilon
        self.epsilon_update_frequency = epsilon_update_frequency

    def _update_epsilon(self):
        self.total_actions += 1
        if self.total_actions % self.epsilon_update_frequency == 0:
            self.epsilon = max(self.total_actions / self.grad_epsilon + self.initial_epsilon, self.final_epsilon)
            if self.total_actions % 1000 == 0:
                tf.summary.scalar(f'{self.name} agent epsilon', self.epsilon, self.total_actions)
                tf.summary.scalar(f'Epsilon', self.epsilon, self.total_actions)

    def save(self, location: str = 'training/results/checkpoints/'):
        """
        Saves the agent neural networks

        Args:
            location: Save location
        """
        # Set the location to save the model and setup the directory
        path = f'{os.getcwd()}/{location}/{self.save_folder}'
        if not os.path.exists(path):
            os.makedirs(path)

        # Save the model network weights to the path
        self.model_network.save_weights(f'{path}/{self.name.replace(" ", "_")}')

    def _train(self, states: tf.Tensor, actions: tf.Tensor,
               next_states: tf.Tensor, rewards: tf.Tensor, dones: tf. Tensor) -> float:
        # Actions are discrete so cast to int32 from float32
        actions = tf.cast(actions, tf.int32)

        network_variables = self.model_network.trainable_variables
        with tf.GradientTape() as tape:
            tape.watch(network_variables)

            # Calculate the state q values for the actions
            state_q_values = self.model_network(states)
            state_action_indexes = tf.stack([tf.range(self.batch_size), actions], axis=-1)
            states_actions_q_values = tf.gather_nd(state_q_values, state_action_indexes)

            # Calculate the next state q values for the next actions (important as a separate function for double dqn)
            next_states_actions_q_values = self._compute_next_q_values(next_states)

            # Calculate the target using the rewards, discount factor, next q values and dones
            # noinspection PyTypeChecker
            target = tf.stop_gradient(rewards + self.discount_factor * next_states_actions_q_values * dones)

            # Calculate the element wise loss
            loss = self.error_loss_fn(target, states_actions_q_values)

        # Backpropagation the loss through the network variables and apply the changes to the network
        gradients = tape.gradient(loss, network_variables)
        self.optimiser.apply_gradients(zip(gradients, network_variables))

        # Check if to update the target, if so update each variable at a time using the target update tau variable
        if self.total_updates % self.training_freq == 0:
            ReinforcementLearningAgent._update_target_network(self.model_network, self.target_network,
                                                              self.target_update_tau)

        return loss

    def _compute_next_q_values(self, next_states: tf.Tensor):
        next_state_q_values = self.target_network(next_states)
        next_actions = tf.math.argmax(next_state_q_values, axis=1, output_type=tf.int32)
        next_state_action_indexes = tf.stack([tf.range(self.batch_size), next_actions], axis=-1)
        return tf.gather_nd(next_state_q_values, next_state_action_indexes)


@gin.configurable
class TaskPricingDqnAgent(DqnAgent, TaskPricingRLAgent):
    """
    Task Pricing DQN agent
    """

    def __init__(self, agent_name: Union[int, str], network: tf.keras.Model, epsilon_steps=50000, **kwargs):
        assert network.input_shape[-1] == self.network_obs_width

        DqnAgent.__init__(self, network, epsilon_steps=epsilon_steps, **kwargs)
        name = f'Task pricing Dqn agent {agent_name}' if type(agent_name) is int else agent_name
        TaskPricingRLAgent.__init__(self, name, **kwargs)

    def _get_action(self, auction_task: Task, allocated_tasks: List[Task], server: Server, time_step: int,
                    training: bool = False) -> float:
        if training:
            self._update_epsilon()
            if rnd.random() < self.epsilon:
                return float(rnd.randint(0, self.num_actions-1))

        observation = tf.expand_dims(self._network_obs(auction_task, allocated_tasks, server, time_step), axis=0)
        q_values = self.model_network(observation)
        action = tf.math.argmax(q_values, axis=1, output_type=tf.int32)
        return action


@gin.configurable
class ResourceWeightingDqnAgent(DqnAgent, ResourceWeightingRLAgent):
    """
    Resource weighting DQN agent
    """

    def __init__(self, agent_name: Union[int, str], network: tf.keras.Model, epsilon_steps=30000, **kwargs):
        assert network.input_shape[-1] == self.network_obs_width

        DqnAgent.__init__(self, network, epsilon_steps=epsilon_steps, **kwargs)
        name = f'Resource weighting Dqn agent {agent_name}' if type(agent_name) is int else agent_name
        ResourceWeightingRLAgent.__init__(self, name, **kwargs)

    def _get_actions(self, tasks: List[Task], server: Server, time_step: int,
                     training: bool = False) -> Dict[Task, float]:
        if training:
            self._update_epsilon()

            actions = {}
            for task in tasks:
                if rnd.random() < self.epsilon:
                    actions[task] = float(rnd.randint(0, self.num_actions-1))
                else:
                    observation = tf.expand_dims(self._network_obs(task, tasks, server, time_step), axis=0)
                    q_values = self.model_network(observation)
                    actions[task] = float(tf.math.argmax(q_values, axis=1, output_type=tf.int32))
            return actions
        else:
            observations = tf.convert_to_tensor([self._network_obs(task, tasks, server, time_step) for task in tasks],
                                                dtype='float32')
            q_values = self.model_network(observations)
            actions = tf.math.argmax(q_values, axis=1, output_type=tf.int32)
            return {task: float(action) for task, action in zip(tasks, actions)}


@gin.configurable
class DdqnAgent(DqnAgent, ABC):
    """
    Implementation of a double deep q network agent based on the following paper
    Double DQN agent implemented based on Deep Reinforcement Learning with Double Q-learning
        (https://arxiv.org/abs/1509.06461)
    """

    def __init__(self, network: tf.keras.Model, **kwargs):
        DqnAgent.__init__(self, network, **kwargs)

    def _compute_next_q_values(self, next_states):
        target_q_values = self.target_network(next_states)
        target_actions = tf.math.argmax(target_q_values, axis=1, output_type=tf.int32)
        target_action_indexes = tf.stack([tf.range(self.batch_size), target_actions], axis=-1)

        model_q_values = self.model_network(next_states)
        return tf.gather_nd(model_q_values, target_action_indexes)


@gin.configurable
class TaskPricingDdqnAgent(DdqnAgent, TaskPricingDqnAgent):
    """
    Task pricing double dqn agent
    """

    def __init__(self, agent_num: int, network: tf.keras.Model, **kwargs):
        DdqnAgent.__init__(self, network, **kwargs)
        TaskPricingDqnAgent.__init__(self, f'Task pricing Double Dqn agent {agent_num}', network, **kwargs)


@gin.configurable
class ResourceWeightingDdqnAgent(DdqnAgent, ResourceWeightingDqnAgent):
    """
    Resource weighting double dqn agent
    """

    def __init__(self, agent_num: int, network: tf.keras.Model, **kwargs):
        DdqnAgent.__init__(self, network, **kwargs)
        ResourceWeightingDqnAgent.__init__(self, f'Resource weighting Double Dqn agent {agent_num}', network, **kwargs)


@gin.configurable
class DuelingDQN(DdqnAgent, ABC):
    """
    Implementations of a dueling DQN agent based on the following papers
    Dueling DQN agent based on Dueling Network Architectures for Deep Reinforcement Learning
        (https://arxiv.org/abs/1511.06581)
    """

    def __init__(self, network: tf.keras.Model, double_loss: bool = True, **kwargs):
        DqnAgent.__init__(self, network, **kwargs)
        self.double_loss = double_loss

    def _compute_next_q_values(self, next_states):
        if self.double_loss:
            target_q_values = self.target_network(next_states)
            next_actions = tf.math.argmax(target_q_values, axis=1, output_type=tf.int32)
            next_state_q_values = self.model_network(next_states)
        else:
            next_state_q_values = self.target_network(next_states)
            next_actions = tf.math.argmax(next_state_q_values, axis=1, output_type=tf.int32)

        action_indexes = tf.stack([tf.range(self.batch_size), next_actions], axis=-1)
        return tf.gather_nd(next_state_q_values, action_indexes)


@gin.configurable
class TaskPricingDuelingDqnAgent(DuelingDQN, TaskPricingDqnAgent):
    """
    Task pricing dueling DQN agent
    """

    def __init__(self, agent_num: int, network: tf.keras.Model, **kwargs):
        DuelingDQN.__init__(self, network, **kwargs)
        TaskPricingDqnAgent.__init__(self, f'Task pricing Dueling Dqn agent {agent_num}', network, **kwargs)


@gin.configurable
class ResourceWeightingDuelingDqnAgent(DuelingDQN, ResourceWeightingDqnAgent):
    """
    Resource Weighting Dueling DQN agent
    """

    def __init__(self, agent_num: int, network: tf.keras.Model, **kwargs):
        DuelingDQN.__init__(self, network, **kwargs)
        ResourceWeightingDqnAgent.__init__(self, f'Resource weighting Dueling Dqn agent {agent_num}', network, **kwargs)


@gin.configurable
class CategoricalDqnAgent(DqnAgent, ABC):

    def __init__(self, network: tf.keras.Model, max_value: float = -20.0, min_value: float = 25.0,
                 **kwargs):
        DqnAgent.__init__(self, network, **kwargs)

        self.v_min = min_value
        self.v_max = max_value
        self.num_atoms: int = network.output_shape[2]
        self.delta_z = (max_value - min_value) / self.num_atoms
        self.support = tf.range(min_value, max_value, self.delta_z, dtype=tf.float32)

    def _train(self, states: tf.Tensor, actions: tf.Tensor, next_states: tf.Tensor, rewards: tf.Tensor,
               dones: tf.Tensor) -> float:
        rewards = tf.expand_dims(rewards, axis=-1)
        dones = tf.expand_dims(dones, axis=-1)
        actions = tf.cast(actions, tf.int32)

        network_variables = self.model_network.trainable_variables
        with tf.GradientTape() as tape:
            tape.watch(network_variables)

            # q_logits contains the Q-value logits for all actions.
            q_logits = self.model_network(states)
            action_indexes = tf.stack([tf.range(self.batch_size), actions], axis=-1)
            chosen_action_logits = tf.gather_nd(q_logits, action_indexes)

            # Next q_logits
            next_target_logits = self.target_network(next_states)
            next_target_q_values = tf.reduce_sum(self.support * next_target_logits, axis=-1)
            next_actions = tf.math.argmax(next_target_q_values, axis=1, output_type=tf.int32)
            next_action_indexes = tf.stack([tf.range(self.batch_size), next_actions], axis=-1)
            next_q_distribution = tf.gather_nd(next_target_logits, next_action_indexes)

            # Project the sample Bellman update \hat{T}Z_{\theta} onto the original
            # support of Z_{\theta} (see Figure 1 in paper).
            tiled_support = tf.ones((self.batch_size, self.num_atoms)) * self.support

            target_support = rewards + self.discount_factor * tiled_support * dones

            # clipped_support = `[\hat{T}_{z_j}]^{V_max}_{V_min}` in Eq7.
            clipped_support = tf.expand_dims(tf.clip_by_value(target_support, self.v_min, self.v_max), axis=1)
            tiled_support = tf.tile([clipped_support], [1, 1, self.num_atoms, 1])
            reshaped_target_support = tf.reshape(tf.ones([self.batch_size, 1]) * self.support,
                                                 [self.batch_size, self.num_atoms, 1])
            # numerator = `|clipped_support - z_i|` in Eq7.
            numerator = tf.abs(tiled_support - reshaped_target_support)
            quotient = 1 - (numerator / self.delta_z)
            clipped_quotient = tf.clip_by_value(quotient, 0, 1)

            # inner_prod = `\sum_{j=0}^{N-1} clipped_quotient * p_j(x', \pi(x'))`
            inner_prod = clipped_quotient * tf.expand_dims(next_q_distribution, axis=1)
            projection = tf.reduce_sum(inner_prod, 3)[0]

            # Target distribution
            target_distribution = tf.stop_gradient(projection)

            loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(target_distribution, chosen_action_logits))

        grads = tape.gradient(loss, network_variables)
        self.optimiser.apply_gradients(zip(grads, network_variables))

        # Check if to update the target, if so update each variable at a time using the target update tau variable
        if self.total_updates % self.training_freq == 0:
            ReinforcementLearningAgent._update_target_network(self.model_network, self.target_network,
                                                              self.target_update_tau)

        return loss


@gin.configurable
class TaskPricingCategoricalDqnAgent(CategoricalDqnAgent, TaskPricingRLAgent):

    def __init__(self, agent_num: int, network: tf.keras.Model, **kwargs):
        CategoricalDqnAgent.__init__(self, network, **kwargs)
        TaskPricingRLAgent.__init__(self, f'Task pricing C51 agent {agent_num}', **kwargs)

    def _get_action(self, auction_task: Task, allocated_tasks: List[Task], server: Server, time_step: int,
                    training: bool = False):
        if training:
            self._update_epsilon()
            if rnd.random() < self.epsilon:
                return float(rnd.randint(0, self.num_actions - 1))

        observation = tf.expand_dims(self._network_obs(auction_task, allocated_tasks, server, time_step), axis=0)
        q_values = tf.reduce_sum(self.support * self.model_network(observation), axis=-1)
        action = tf.math.argmax(q_values, axis=1, output_type=tf.int32)
        return action


@gin.configurable
class ResourceWeightingCategoricalDqnAgent(CategoricalDqnAgent, ResourceWeightingRLAgent):

    def __init__(self, agent_num: int, network: tf.keras.Model, **kwargs):
        CategoricalDqnAgent.__init__(self, network, **kwargs)
        ResourceWeightingRLAgent.__init__(self, f'Resource weighting C51 agent {agent_num}', **kwargs)

    def _get_actions(self, tasks: List[Task], server: Server, time_step: int,
                     training: bool = False) -> Dict[Task, float]:
        if training:
            self._update_epsilon()

            actions = {}
            for task in tasks:
                if rnd.random() < self.epsilon:
                    actions[task] = float(rnd.randint(0, self.num_actions - 1))
                else:
                    observation = tf.expand_dims(self._network_obs(task, tasks, server, time_step), axis=0)
                    q_values = self.model_network(observation) * self.support
                    actions[task] = float(tf.math.argmax(q_values, axis=1, output_type=tf.int32))
            return actions
        else:
            observations = tf.convert_to_tensor([self._network_obs(task, tasks, server, time_step) for task in tasks],
                                                dtype='float32')
            q_values = tf.reduce_sum(self.support * self.model_network(observations), axis=-1)
            actions = tf.math.argmax(q_values, axis=1, output_type=tf.int32)
            return {task: float(action) for task, action in zip(tasks, actions)}
