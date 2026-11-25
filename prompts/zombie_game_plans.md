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
This task has been done. The ontology specifications are stored in the folder "ontology". More specifically, the file "zombie_game_ontology_v0.1.md" provides the ontology written in Markdown. And, formalized ontology specifications are in the folder "ontology/formal_v0.1".



### TASK 2: Implement Zombie Game Simulation Framework

- The implementation plan has done, in files: "prompts/task_2_implementation_plan.md" and "prompts/task_2_action_and_validation_matrix.md".
- The test suite has been created, in the folder: "tests".
- The first implementation is finished. The following folders together with files therein are created: "artifacts", "build", "configs", "diagnostics", "docs", "src", "gui", "implementation_checks", "scripts", and "training".

Your current step is to test the current implementation against the test suite. I have given a few dry runs of the current implementation, and I found a few issues stated below. During the testing, you also must address the issues:
  - The following error message pops up, whenever I create and start a new experiment: "'Unknown run b9a2d901195b41aaa6d895cf8326cb35'".
  - The following error message pops up during the runtime: "Unexpected token 'I', "Internal S"... is not valid JSON".
  - The following error message pops up during the runtime: "Stale control generation: refresh generation 2".
  - I tried to use multiple workers, e.g., 10 and 20 (because my computer supports 24 logical CPU cores), but constantly there are only 4 logical CPU cores staying at high utilization during the runtime, regardless of the number of workers set in the configuration. I want the implementation to fully utilize the CPU resources, and the implementation must be able to choose an appropriate number of workers for different hardware environments. 
  - I found that the simulation might not fully stop after pressing the "Pause run" button on the GUI interface.
  - I need a button for terminating the current run without save. 

If addressing any of the above issues or any issues identified during the testing requires to change the problem formulation or the ontology, you must pause and explicitly and clearly explain the issue and your proposal of changes, and you must wait for my approval before continuing. 

If the problem formulation and/or the ontology must be modified, you must:
  - 1. Comprehensively and rigorously evaluate whether the ontology, fully or partially, needs to be refactored, redefined, or reformalized.
  - 2. If the ontology must be refactored, redefined, or reformalized, you must propose a modification plan, explicitly explaning what changes will be made, and wait for my review and approval before continuing.
  - 3. If the ontology is confirmed to be modified, you must proceed with it rigorously. After the modifications, you must rigorously validate the modified ontology.
  - 4. After the new ontology is successfully created and validated, if any, a new test suite must be provided in accordance with the new ontology.
  - 5. After the new test suite is successfully created, you must refine the implementation of the Zombie Game Simulation Framework. 
  - 6. After the implementation refinement, you must test the new implementation against the new test suite rigorously.