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

Your current step is to fix the following identified issues.
  - When using GUI, for a run, after pressing "Terminate without save", the run is placed in "SAVED RUNS" of the sidebar to the left anyway. Also, after pressing "Terminate without save", many CPU cores keep running. 
    - First, you must check whether pressing "Terminate without save" actually terminates the current run. 
    - Second, you must check whether runs terminated without save are not saved. 
  - After starting GUI from the launcher "simulate", using the option "9 Open the GUI", the GUI will be pending on a message "Initializing the world… Validating geometry and placing the requested population." for a relatively long time. You must check if this is actually normal.
  - When I try to start a new simulation via the "New Experiment" button, choose "Small 20 agents", and press "Validate", an error message pops up: "Unexpected end of JSON input".
  - When using GUI, in the "New Experiment" configuration interface, for every input box, if I keep pressing the "back" key to delete the number, eventually it will show "0", but after that, if I manually input a new number, this "0" will not be replaced by the input numbers, rather it is kept as the first digit of the new number. 
    - The correct behavior should be: I can completely remove all digits of the default number, and input a new number without "0" as the leading digit.
  - When using GUI, in the "New Experiment" configuration interface, if I manually input the numbers of Humans and Zombies, the numbers of agents for roles are not automatically updated, which leads to failures of configuration validation.
    - A better way to implement this is: first, the percentage of agents for each role can be explicitly configured in GUI; second, the number of agents for the role is automatically updated whenever the numbers of Humans and Zombies are changed and/or the percentage for the role is changed; and third, all percentages and the numbers of agents for all roles must be kept consistent. 
  - When running the simulation using the default configurations, such as "Small 20 agent" and "Ontology baseline 1,000 agents", the "Statistics" view may show no curves, i.e., the view is empty. Be cautious that this issue may be conditioned on some factors unknown to me, because sometimes the view does show curves. In addition, when the "Statistics" view does show curves, the time axis is not updated along with the time elapse. 
  - I have not seen the "Cohorts", "Events", and "Comparison" views work. I'm not sure if those views actually work.
    - You must check whether they work correctly. If not, you must fix them. Otherwise, you must explicitly explain how to use them in a user guide.
  - A comprehensive user guide is needed. The desired user guide must be as friendly as possible.
  - When using GUI, in the "New Experiment" configuration interface, the "Human decision model" is empty by default, I have no idea what input is expected. You must explicitly explain this.

If addressing any of the above issues or any issues identified during the testing requires to change the problem formulation or the ontology, you must pause and explicitly and clearly explain the issue and your proposal of changes, and you must wait for my approval before continuing. 

If the problem formulation and/or the ontology must be modified, you must:
  - 1. Comprehensively and rigorously evaluate whether the ontology, fully or partially, needs to be refactored, redefined, or reformalized.
  - 2. If the ontology must be refactored, redefined, or reformalized, you must propose a modification plan, explicitly explaning what changes will be made, and wait for my review and approval before continuing.
  - 3. If the ontology is confirmed to be modified, you must proceed with it rigorously. After the modifications, you must rigorously validate the modified ontology.
  - 4. After the new ontology is successfully created and validated, if any, a new test suite must be provided in accordance with the new ontology.
  - 5. After the new test suite is successfully created, you must refine the implementation of the Zombie Game Simulation Framework. 
  - 6. After the implementation refinement, you must test the new implementation against the new test suite rigorously.