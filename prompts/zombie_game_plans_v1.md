# Zombie Game Simulation Framework

## Overview
It is planned to develop an agent-based model framework, named Zombie Game Simulation Framework. In this simulation, multiple humans and zombies, as agents, will be created, each agent may further have a role, e.g., Doctor and Warrior for humans, and Tyrant for zombies. A variety of interactions occur between humans and zombies, including human-human and zombie-zombie interactions. In addition, agents may take some actions according to the local environment they stand in. 

Each agent has a set of attributes, such as a unique ID, its current life value, its status (e.g., LIVE, INFECTED, DEAD, and some others), its position (e.g., x-coordinate and y-coordinate), its sensing range, and others. Agents of different types may also have type-specific or role-specific attributes, such as whether it has medical or fighting skills for humans, and the virulence of a zombie. The state-wise attributes will change along the evolution of the simulation.

More importantly, each agent needs to have a model in the backend to make decisions on taking actions to interact with other agents or the environment. A variety of models may be tested. 

From the simulation perspective, the efficiency is crucial, and thus appropriate parallelism techniques may be needed, especially when the simulation is scaled up. The full evolution of each run of the simulation must be captured and properly stored for subsequent studies. 

Many studies can be proceeded based on the simulation, such as the dynamics of populations, learning optimal decision-making models for different types of agents, counterfactual analysis with external controls, and emergence phenomena, such as emergent group behaviors. 

We will generate an ontology for the simulation first. The ontology describes the Zombie Game at the semantic level without implementations. The ontology will be reviewed and edited until we are satisfied. After that, we implement the simulation framework based on the ontology.


## Tasks

### TASK 1: Build Zombie Game Simulation Ontology
A comprehensive and detailed ontology for the Zombie Game simulation is desired. 

**Playground**
For early stages of this project, we can use a bounded Euclidean space, i.e., a plain, to set up the playground. 

The size of the playground needs to be specified:
- `length`: (Real) The length of the playground.
- `width`: (Real) The width of the playground.

> [!todo]
> - You must specify appropriate `length` and `width` to make the simulation significant enough.


**Agents**
Basic agent *attributes* need to be defined. The following attributes may be needed:
- `ID`: (Integer) Unique ID for each agent.
- `type`: (Categorical) `Human` or `Zombie`.
- `role`: (Categorical) The role of the agent, if any, e.g., `DOCTOR` and `WARRIOR` for humans.
- `status`: (Categorical) Such as `HEALTHY`, `INFECTED`, `DEAD`, and some other potential statuses for both humans and zombies.
- `life`: (Integer) The life value of the agent. It takes values in a range, e.g., from 0 to 100. 
- `x`: (Real) The x-coordinate of the agent.
- `y`: (Real) The y-coordinate of the agent.
- `speed`: (Real) The speed of movement.
- `sense_r`: (Real) The sensing radius.

Type-specific attributes are needed for humans and zombies. 

Role-specific attribute are needed for each role. (The role system is explained below.)

> [!todo]
> - You must rigorously identify all necessary agent attributes and define them. 
> - You must be creative and define some type-specific attributes for both humans and zombies.

In addition to attributes, each agent has some *actions* to takes at every moment the agent is considered during the evolution of the simulation. 

The decision-making of actions for each agent is driven by backend models (e.g., reinforcement models or AI-driven models). When such a model makes decisions for an agent, it is assumed that the model can retrieve information of the environment and the states of its neighboring agents that are in the sensing range of the considered agent.

For all agents, the action `move` is mandatory. The validity of the movement is constrained by the `speed` of the considered agent and the range of the playground. The direction to move is the result of a decision-making by the agent. 

> [!todo]
> - You must be creative and add some actions for both humans and zombies. 


**Role System**
For agents, we need to design a *role system*, so that we are enabled to easily introduce any appropriate roles as needed. 

Each role has its specific *attributes* and *actions*. 

> [!todo]
> - You must be creative and define some roles for both humans and zombies for the initial version of this simulation, with their attributes and actions well defined.


### TASK 2: Implement Zombie Game Simulation Framework

**Simulation Logic**
> [!todo]
> - You must follow the ontology built in TASK 1 and implement the Zombie Game logic. 

**Agent Intelligence**
One of the goals of this simulation framework is to introduce intelligence to agents through machine learning or other methods. In other words, the behaviors of the agents, i.e., their actions, will not be kept hardcoded. It is required to enable extensions for agents to do intelligent decision-making. This is why it is called a *framework*.

> [!todo]
> - You must implement a default version of all actions for the agents. And, the default version must be nontrivial enough.
> - You must rigorously design and implement the extension interfaces for introducing more sophisticated agent actions, such as reinforcement learning models. In addition, you must also provide concrete design and guide for training and testing those models. 


**Data Storage**
The live data of the simulation (such as agent attributes and environment states) can be large. And, the simulation program needs to access the live data frequently.

A storage framework for storing live data is required to support various storage solutions, such as in-memory data structures and databases.

On the other hand, to support subsequent studies, the evolution of the simulation needs to be recorded. Taking periodic snapshots of the entire simulation may be a solution for recording the evolution. The efficiency of both storage and access is important. 

> [!todo]
> You must rigorously design and implement the solution to handle the live data and the solution to storing the evolution of the simulation concretely.


**Evolution**
The simulation needs to keep producing dynamics. This is a core building block of the simulation. 

The simulation can be synchronous or asynchronous. The asynchronous paradigm might be more "real". 

> [!todo]
> - You must consider all involved factors and decide whether the simulation is asynchronous.

In the evolution, agents raise events, such as movement, agent-agent interactions, and agent-environment interactions. If we want the simulation to run efficiently, the events need to be processed in parallel, as much as possible. At the same time, the effects of the events need to be guaranteed to be consistent. For example, if a human meets a zombie, at almost the same moment, the human tries to kill the zombie, and the zombie tries to kill the human too. However, only one of the two events can take effect, but not both. 

> [!todo]
> - You must concretely implement the event management and processing with appropriate parallelism techniques. 
> - You also must explain in detail the algorithms used to implement the parallelism. 


**Hyperparameter & Instance Management**
A simulation instance is required to be configurable, such as its initial states. Having a reasonable and convenient hyperparameter and instance management system is crucial. For example, if we configure a simulation instance with a few hyperparameters, the live data, the recorded simulation data, experimental results from subsequent studies, and so on should be well organized in a place specific to this instance. 

> [!todo]
> - You must design and implement this hyperparameter & instance management system.


## General Requirements
1. You must address TASK 1 first, and output the ontology explicitly for me to download. I will review the ontology, and send you commands to proceed.
2. Your ontology output must be human-readable. If any ontology standards are used, you must explain which standards are used and why you choose them. 



