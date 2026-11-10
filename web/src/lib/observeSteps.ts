import { api } from "./api";

/** Live-observation steps for a browser task (Aasan Companion extension); edited by the course author only. */
export interface ObserveStep { id?: string; label: string; url_pattern: string; text: string }
export interface ObserveSteps { steps: ObserveStep[]; hosts: string[]; origins: string[]; optional: boolean }

const url = (activityId: number) => `/api/ext/authoring/activities/${activityId}/steps/`;

export const observeSteps = {
  get: (activityId: number) => api<ObserveSteps>(url(activityId)),
  save: (activityId: number, steps: ObserveStep[], optional: boolean) => api<ObserveSteps>(url(activityId), { method: "PUT", json: { steps, optional } }),
};
