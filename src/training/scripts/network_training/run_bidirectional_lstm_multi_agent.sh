#!/bin/bash

#SBATCH --partition=lyceum
#SBATCH --time=6:00:00

cd ~/Online-Flexible-Resource-Allocation/src/

module load conda
source activate py37env

echo 'Running Bidirectional LSTM Network DQN multi-agent'
python -m  training.scripts.network_training.bidirectional_lstm_multi_agent