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
export type Feedback = S['FeedbackOut'];
export type Vote = Feedback['vote'];
export type Mute = S['MuteOut'];
export type MuteIn = S['MuteIn'];
export type DayReadOut = S['DayReadOut'];
export type SearchResult = S['SearchResult'];
export type SearchResults = S['SearchResults'];
export type SettingsView = S['SettingsOut'];
export type NotifyChannel = S['NotifyChannel'];
export type NotifyTestOut = S['NotifyTestOut'];
export type Overrides = S['OverridesIn'];
export type FocusArea = S['FocusOut'];
export type FocusIn = S['FocusIn'];
export type FocusTier = FocusArea['tier'];
export type SourceConfig = S['SourceConfig'];
export type SourceIn = S['SourceIn'];
export type SourceKind = SourceIn['kind'];
export type FeedTestIn = S['FeedTestIn'];
export type FeedTestOut = S['FeedTestOut'];
