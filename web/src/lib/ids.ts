/** True for a route id that can never match a record (missing, NaN, 0, negative). */
export const badId = (id: number) => !Number.isInteger(id) || id <= 0;
