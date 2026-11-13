# Zombie Game Simulation Framework

## Overview
It is planned to develop an agent-based model framework, named Zombie Game Simulation Framework. In this simulation, multiple humans and zombies, as agents, will be created, each agent may further have a role, e.g., Doctor and Warrior for humans, and Tyrant for zombies. A variety of interactions occur between humans and zombies, including human-human and zombie-zombie interactions. In addition, agents may take some actions according to the local environment they stand in. 

Each agent has a set of attributes, such as a unique ID, its current life value, its status (e.g., LIVE, INFECTED, DEAD, and some others), its position (e.g., x-coordinate and y-coordinate), its sensing range, and others. Agents of different types may also have type-specific or role-specific attributes, such as whether it has medical or fighting skills for humans, and the virulence of a zombie. The state-wise attributes will change along the evolution of the simulation.

More importantly, each agent needs to have a model in the backend to make decisions on taking actions to interact with other agents or the environment. A variety of models may be tested. 

From the simulation perspective, the efficiency is crucial, and thus appropriate parallelism techniques may be needed, especially when the simulation is scaled up. The full evolution of each run of the simulation must be captured and properly stored for subsequent studies. 

Many studies can be proceeded based on the simulation, such as the dynamics of populations, learning optimal decision-making models for different types of agents, counterfactual analysis with external controls, and emergence phenomena, such as emergent group behaviors. 

We will generate an ontology for the simulation first. The ontology describes the Zombie Game at the semantic level without implementations. The ontology will be reviewed and edited until we are satisfied. After that, we implement the simulation framework based on the ontology.


## Tasks

### TASK 2: Implement Zombie Game Simulation Framework

Based on the ontology specifications created in TASK 1, the simulation framework is concretely implemented in this task.

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





