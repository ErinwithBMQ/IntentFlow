export const initialTasks = [
  { id: "task-1", title: "Review the interaction notes", completed: true },
  { id: "task-2", title: "Implement the add-task flow", completed: false },
  { id: "task-3", title: "Run the behavior tests", completed: false },
];

export function countOpenTasks(tasks) {
  return tasks.filter((task) => !task.completed).length;
}

export function createTaskElement(task) {
  const item = document.createElement("li");
  item.className = task.completed ? "task-item task-item--completed" : "task-item";
  item.dataset.taskId = task.id;

  const marker = document.createElement("span");
  marker.className = "task-marker";
  marker.setAttribute("aria-hidden", "true");

  const title = document.createElement("span");
  title.textContent = task.title;

  item.append(marker, title);
  return item;
}
