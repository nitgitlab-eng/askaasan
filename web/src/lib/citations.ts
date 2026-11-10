/** Where a mentor reply's facts came from: the learner's document (numbered chips) or web pages the server searched. */

export interface DocCitation {
  kind?: undefined;
  n: number;
  page: number;
  chunk_id: number;
  snippet: string;
}

/** A web page the reply used (from the server's search results, never from the model's text). */
export interface WebSource {
  kind: "web";
  title: string;
  url: string;
}

export type Citation = DocCitation | WebSource;

export const isWebSource = (c: Citation): c is WebSource => c.kind === "web";
