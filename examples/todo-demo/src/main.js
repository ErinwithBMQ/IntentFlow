import "./styles.css";
import { countOpenTasks, createTaskElement, initialTasks } from "./tasks";

const taskList = document.querySelector("#task-list");
const taskCount = document.querySelector("#task-count");
const taskForm = document.querySelector("#task-form");

for (const task of initialTasks) {
  taskList.append(createTaskElement(task));
}

taskCount.textContent = `${countOpenTasks(initialTasks)} open`;

taskForm.addEventListener("submit", (event) => {
  event.preventDefault();
});

