# -*- coding: utf-8 -*-
"""DQN_target.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1iE4I6bjC2B7wkra5JzDK0oyv-D3ODtW2
"""

#Dominic Zhao

# Commented out IPython magic to ensure Python compatibility.
# %tensorflow_version 2.x

import tensorflow as tf
import numpy as np
import pandas as pd
import gym
print("ok")
from collections import deque

"""Preprocessing the pixel inputs (as specified in the paper). the raw atari frames are 210 to 160 pixels. We down-sample it to 110x84 images and grey scale."""

def grayscale(image):
    # take the mean along rbg values to get one output which is the grayscale, no each pixel has 
    #one value on the gray scale 
    #find a way to store it more efficiently, when its in uint8 we have some problems with fit_batcg
    return np.mean(image,axis=2).astype(np.uint8)

def downsample(image):
    #for each 2 pixel, we take one (getting rid of half the pixels)
    return (image[::2,::2])
def preprocess(image):
    #since we are going to use convolutions, we also want to reshape to add a last dimension (channels)
    #if only one image per stack, we need to expand dims
    return grayscale(downsample(image))

"""As explained in the DQN paper, the reward is changed to the sign of the reward (+1, -1 or 0)"""

def transform_reward(reward):
    return np.sign(reward)

"""We now create the DQN model."""

stack_size = 4 # We stack 4 frames

# Initialize deque with zero-images one array for each image
stacked_frames  =  deque([np.zeros((105,80), dtype=np.int) for i in range(stack_size)], maxlen=4)

def stack_frames(stacked_frames, state, is_new_episode):
    # Preprocess frame
    frame = preprocess(state)
    if is_new_episode:
        # Clear our stacked_frames
        stacked_frames = deque([np.zeros((105,80), dtype=np.int) for i in range(stack_size)], maxlen=4)
        
        # Because we're in a new episode, copy the same frame 4x
        stacked_frames.append(frame)
        stacked_frames.append(frame)
        stacked_frames.append(frame)
        stacked_frames.append(frame)
        
        # Stack the frames
        stacked_state = np.stack(stacked_frames, axis=2)
        
    else:
        # Append frame to deque, automatically removes the oldest frame
        stacked_frames.append(frame)

        # Build the stacked state (first dimension specifies different frames)
        stacked_state = np.stack(stacked_frames, axis=2) 
    
    return stacked_state, stacked_frames

def fit_batch(model,gamma,start_states,actions,rewards,next_states,is_terminal,target_model):
    '''this is one Q learning iteration. 
    To be able to have multiple output (instead of one output per action)
    We will multiply the networks output by a mask, which is the one-hot encoded actions 
    so output will be zero unless it's an action we saw. Much faster to have one output per action.
    params:
    - model : the Q network
    -gamma: discount factor
    -start_states: np array of starting states
    -actions: np array of one-hot encoded actions corresponding to the start-states
    -rewards: np array of rewards corresponding to start-states and actions
    -next_states: np of array of resulting states corresponding to start states
    -is terminal: numpy boolean array of if the resulting state is terminal
    -possible_actions: number of possible actions, to determine for the one hot encoding
    '''
    actions=np.array(actions) #comes in as a tuple
    actions_one_hot=np.array([possible_actions[choice] for choice in actions])
 
    # predict all the Q values for each next state. we want to consider all actions so the mast is ones
    #we use a different target model that is updated every N steps.
    next_Q_values=target_model.predict([next_states,np.ones(actions_one_hot.shape).tolist()])
    actions_one_hot=actions_one_hot.tolist()
    #the model only works if the inputs are lists, weirdly
    
    #all the Q values for all the next_states, at all the possible actions
    # if the resulting state is terminal, the Q value is 0 by definition
    next_Q_values[is_terminal]=0
    #reward+gamma*max of next state Q value
    # in the case, if terminal, Q_value is just r
    #in the paper, Q_values correspond to y, the targets
    Q_values=rewards+gamma*np.max(next_Q_values,axis=1)
   

    # we perform a gradient descent step on (y-Q)^2, Q being the output of our current Q network
    #multiply target by action to only consider the actions we chose, since in the algo the chosen action
    model.fit([start_states,actions_one_hot],actions_one_hot*Q_values[:,None], epochs=1, batch_size=len(start_states),verbose=0)
    
    #Since the input only has a size of len(start_states), this fit function only does one step.

def atari_model(n_actions):
    # Shape of the input and number of chanels (height ,width ,channels)
    # Since we preprocessed the pixels are divided by 2
    SHAPE=(105,80,4)  #stack of 4 windows
    SHAPE2=(n_actions,)
    #defining 2 inputs for the keras model. Eventually we will have a custom neural net so this won't be need
    # for the inputs we have the image and the one hot actions mask
    frames_inputs=tf.keras.layers.Input(SHAPE,name="frames")
    actions_input=tf.keras.layers.Input(SHAPE2, name="mask")
    #normalize the frames input
    normalized=tf.keras.layers.Lambda(lambda x: x/255.0)(frames_inputs)
    #The first layer is 16 filters, with kernel of size 8x8, with stride of 4, relu
    conv_1=tf.keras.layers.Conv2D(16,8,4,activation="relu")(normalized)
    #32 filters, 4x4 kernel , stride 2 , relu
    conv_2=tf.keras.layers.Conv2D(32,4,2,activation='relu')(conv_1)
    
    #flattening 
    conv_flattened=tf.keras.layers.Flatten()(conv_2)
    hidden=tf.keras.layers.Dense(256,activation='relu')(conv_flattened)
    #one single output for each action
    output=tf.keras.layers.Dense(n_actions)(hidden)
    #multiply by the mask
    filtered_output=tf.keras.layers.multiply([output,actions_input])
  
    model = tf.keras.Model(inputs=[frames_inputs, actions_input], outputs=filtered_output)
    optimizer=tf.keras.optimizers.RMSprop(lr=0.00025, rho=0.95, epsilon=0.01)
    model.compile(optimizer, loss='mse')
    return model

def q_iteration(env,model,state,iteration,memory,stacked_frames,target_model):
    # Choose epsilon based on the iteration
    # follow the paper to get the epsilon schedule
    epsilon=get_epsilon_for_iteration(iteration)
    #choose the action 
    if np.random.random()<epsilon:
        action=env.action_space.sample()
        #we need to one hot encode
        #action=possible_actions[choice].tolist()
    else:
        action=np.argmax(choose_best_action(model,state))
    new_state,reward,is_done,_=env.step(action)

    #We want the stacked new_state
    new_state, stacked_frames=stack_frames(stacked_frames,new_state,False)


    memory.add(state,action,reward,new_state,is_done)
    # from the memory, sample a batch , and perform one step
    batch=memory.sample_batch(32)
    #sample_batch is of the shape (state, action, rewards,new_state, is_terminal)
    gamma=0.99
    #we can worry about gamma later
    
    #the batch arrives as a list of tuples (state,action,reward,next_state,is_done)
    #we have to unzip
    state_, action_, reward_, next_state_ , is_done_= tuple(zip(*batch))
    fit_batch(model,gamma,state_,action_,reward_,next_state_,is_done_,target_model)
    
    return new_state, reward ,is_done , stacked_frames

"""To implement: 1) Memory class , with add function and sample_batch(number), this is the experience replay buffer
2)get_epsilon_for_iteration, from the schedule
3) choose_best_action (argmax of model(state,action)
"""

class Memory():
    def __init__(self,max_size):
        self.buffer=deque(maxlen=max_size)
    def add(self,state,action,reward,next_state,is_done):
        self.buffer.append((state,action,reward,next_state,is_done))
    def sample_batch(self,batch_size):
        buffer_size=len(self.buffer)
        index=np.random.choice(np.arange(buffer_size),size=batch_size,replace=False)
        return [self.buffer[i] for i in index]

def instantiate_memory(max_size, pretrain_length,possible_actions,stacked_frames):
    #pretrain_length is how much we want to populate the memory before hand.
    #max_size is the maximum size of the memory
    memory=Memory(max_size=max_size)
    for i in range(pretrain_length):
        #if it's first step
        if i==0:
            state=env.reset()
            state,stacked_frames=stack_frames(stacked_frames,state,True)
        action=np.random.randint(1,len(possible_actions))-1
        next_state,reward,done,_=env.step(np.argmax(action))
        next_state,stacked_frames=stack_frames(stacked_frames,next_state,False)
        if done:
            next_state=np.zeros(state.shape)
            memory.add(state,action,reward,next_state,done)
            state=env.reset()
            #if done, it means we are dead
            state,stacked_frames=stack_frames(stacked_frames,state,True)
        else:
            memory.add(state,action,reward,next_state,done)
            state=next_state
            #now we can do another loop
    return memory

def get_epsilon_for_iteration(iteration):
    if iteration<=1000000: 
        return 1-(iteration+1)*0.0000009
    else:
        return 0.1

def choose_best_action(model,state):
    l=[]
    for i in range(possible_actions.shape[0]):
        l.append(state)
    Q_values=model.predict([l,possible_actions.tolist()])
    choice=np.argmax(np.diagonal(Q_values))
    action=possible_actions[choice].tolist()
    return action

"""Let's start training"""

env=gym.make("Qbert-v0")
possible_actions=np.array(np.identity(env.action_space.n,dtype=float).tolist())

#define the hyperparmeters and parameters
total_episodes=50000
max_steps=10000000
#for memory
max_size=1000000
pretrain_length=50000
target_model_update=10000

import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
'''
0 = all messages are logged (default behavior)
1 = INFO messages are not printed
2 = INFO and WARNING messages are not printed
3 = INFO, WARNING, and ERROR messages are not printed


'''

tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.ERROR)

my_dqn=atari_model(len(possible_actions))
target_network=atari_model(len(possible_actions))
stacked_frames  =  deque([np.zeros((105,80), dtype=np.int) for i in range(stack_size)], maxlen=4)
memory=instantiate_memory(max_size,pretrain_length,possible_actions,stacked_frames)
iteration=0
for episode in range(total_episodes):
    #set step to 0
    step=0
    #Initialize rewards of the episode
    episode_rewards=[]
    #for new epsiode, we observe the first state
    state=env.reset()
    state,stacked_frames=stack_frames(stacked_frames,state,True)
    while step<max_steps:
        #performs one q iteration and feed the new_state to state for the next q iteration
        new_state, reward, is_done,stacked_frames=q_iteration(env,my_dqn,state,iteration,memory,stacked_frames,target_network)
        state=new_state
        episode_rewards.append(reward)
        step+=1
        iteration+=1
        if iteration%target_model_update==0:
          target_network=tf.keras.models.clone_model(my_dqn)
          target_network.set_weights(my_dqn.get_weights())
          print("target network updated")
        if is_done:
            print("IS DONE--------------------------------------------")
            step=max_steps
        
            #if is_done , the episode is finished
    print("Episode {}".format(episode),
                 "Total reward: {}".format(np.sum(episode_rewards))
                 )
print("done")

my_dqn.save('dqn.h5') 
from google.colab import files
files.download('dqn.h5')
