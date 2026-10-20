import type { Project } from "@/api";

export function projectLabel(projects: Project[], id: string) {
  return projects.find((project) => project.id === id)?.display_name || id;
}

export function hasDuplicateProjectLabel(projects: Project[], label: string) {
  return (
    projects.filter((project) => (project.display_name || project.id) === label)
      .length > 1
  );
}
