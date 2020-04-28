"""
Tests the linear exploration method used in the DQN agent
"""

# TODO add comments
from agents.rl_agents.agents.ddpg import TaskPricingDdpgAgent, ResourceWeightingDdpgAgent
from agents.rl_agents.agents.dqn import TaskPricingDqnAgent, ResourceWeightingDqnAgent, TaskPricingCategoricalDqnAgent, \
    ResourceWeightingCategoricalDqnAgent
from agents.rl_agents.neural_networks.ddpg_networks import create_lstm_actor_network, create_lstm_critic_network
from agents.rl_agents.neural_networks.dqn_networks import create_lstm_dqn_network, create_lstm_categorical_dqn_network
from env.environment import OnlineFlexibleResourceAllocationEnv


def test_epsilon_policy():
    print()
    # Tests the epsilon policy by getting agent actions that should update the agent epsilon over time
    env, state = OnlineFlexibleResourceAllocationEnv.load_env('agent/settings/actions.env')

    pricing_agents = [
        TaskPricingDqnAgent(0, create_lstm_dqn_network(9, 5)),
        TaskPricingCategoricalDqnAgent(1, create_lstm_categorical_dqn_network(9, 5)),
        TaskPricingDdpgAgent(2, create_lstm_actor_network(9), create_lstm_critic_network(9))
    ]

    weighting_agents = [
        ResourceWeightingDqnAgent(0, create_lstm_dqn_network(9, 5)),
        ResourceWeightingCategoricalDqnAgent(1, create_lstm_categorical_dqn_network(9, 5)),
        ResourceWeightingDdpgAgent(2, create_lstm_actor_network(9), create_lstm_critic_network(9))
    ]

    done = False
    while not done:
        if state.auction_task is not None:
            actions = {
                server: pricing_agents[pos].bid(state.auction_task, tasks, server, state.time_step, training=True)
                for pos, (server, tasks) in enumerate(state.server_tasks.items())
            }
        else:
            actions = {
                server: weighting_agents[pos].weight(tasks, server, state.time_step, training=True)
                for pos, (server, tasks) in enumerate(state.server_tasks.items())
            }
        state, rewards, done, _ = env.step(actions)
