// Named aliases over the generated OpenAPI types (schema.d.ts is never edited by hand).
import type { components } from './schema';

type S = components['schemas'];

export type Story = S['Story'];
export type StorySource = S['SourceOut'];
export type Sections = S['Sections'];
export type Counts = S['Counts'];
export type Gazette = S['Gazette'];
export type DaySummary = S['DaySummary'];
export type DayDetail = S['DayDetail'];
export type DayRun = S['DayRun'];
export type Run = S['RunOut'];
export type RunStarted = S['RunStarted'];
export type SourceStatus = S['SourceStatus'];
export type Bucket = Story['bucket'];
export type Me = S['Me'];
export type LoginIn = S['LoginIn'];
