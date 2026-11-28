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
- The implementation is finished and tested. The following folders together with files therein are created: "artifacts", "build", "configs", "diagnostics", "docs", "src", "gui", "implementation_checks", "scripts", and "training".

**General Requirements for Issue Resolving, Modification, and Refactoring:**
- For both issues and modification as well as refactoring requests, you must:
  - 1. Comprehensively and rigorously evaluate whether the ontology, fully or partially, needs to be refactored, redefined, or reformalized.
  - 2. If the ontology must be refactored, redefined, or reformalized, you must propose a modification plan, explicitly explaning what changes will be made, and wait for my review and approval before continuing.
  - 3. If the ontology is confirmed to be modified, you must proceed with it rigorously. After the modifications, you must rigorously validate the modified ontology.
  - 4. After the new ontology is successfully created and validated, if any, a new test suite must be provided in accordance with the new ontology, if needed.
  - 5. After the new test suite is successfully created, you start refining the implementation of the Zombie Game Simulation Framework, such as fixing issues and fulfilling modification and refactoring requests. 
  - 6. After the implementation refinement, you must test the new implementation against the new test suite rigorously.

- For each identified issue, you must:
  - 1. Briefly explain the causes
  - 2. Propose an effective solution
  - 3. Rigorously justify why the proposed solution can resolve the issue successfully
  - 4. Explicitly report to me the causes, the proposed solution, and the justification
  - 5. Wait for my approval before continuing

- For each modification and refactoring request, you must:
  - 1. Clarify and understand the task
  - 2. Identify the scopes of affected concepts, relations, components, technical details, and other factors in the problem formualtion, ontology, test suite, and current implementation, respectively.
  - 3. Propose a concrete and detailed plan for the request
  - 4. Rigorously justify why the proposed plan can fulfill the request successfully
  - 5. Explicitly report to me the proposed plan and the justification
  - 6. Wait for my approval before continuing

Your current step is to further refine the implementation with in-depth OOP:
  - Many building blocks are still not designed or implemented in OOP, e.g., there is no explicit definitions or inheritance of different types of agents or roles, the events (i.e., activities of agents) may be designed and implemented in a unified definition, the logic of Zombie Game may be decoupled from the module managing system states (i.e., the states of agents and the enirvonment), and the system state management may need to be decoupled from and interfaced to difference choices of underlying storage solutions. These issues may create difficulties in evolving the framework in the near future. You must redesign and reimplement the framework so that it is robust, engineered, flexible, rigorous, and friendly enough to be understood and evolved. 
  - You must add appropriate yet concise enough comments to the code so that human reviewers can understand the design and the implementation easily. 
  - You must re-examine the ontologies to ensure that the refactoring will be consistent with the ontologies.
  - You must re-examine the test suite and modify them so that the refactored implementation will be tested rigorously.
  - After refactoring, you must carefully and rigorously justify that the implementation is actually consistent with ontologies, and you must test the refactored implementation against the updated test suite.
