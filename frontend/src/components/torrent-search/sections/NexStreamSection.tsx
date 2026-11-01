import { useEffect, useState } from 'react';
import { Loader2, Play } from 'lucide-react';
import { TorrentPlayerShell, type TorrentPlayerShellProvider } from '../TorrentPlayerShell.tsx';
import { TvShowCard } from '../TvShowCard.tsx';
import { imdbRatingKey } from '../grouping.ts';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';

export function NexStreamSection({ vm }: { vm: PanelModel }) {
  const { imdbRatingsByKey, loadNexStreamEpisodes, nexStreamEpisodePicker, nexStreamEpisodes, nexStreamEpisodesError, nexStreamEpisodesLoading, nexStreamEpisodesStatus, nexStreamError, nexStreamLoading, nexStreamPlayer, nexStreamResolvingId, nexStreamResults, nexStreamSearchMode, nexStreamSeasons, nexStreamSelectedSeason, playWithNexStream, setNexStreamEpisodePicker, setNexStreamPlayer, switchNexStreamProvider, switchToYenimePlayer } = vm;
  const [playerLoading, setPlayerLoading] = useState(false);
  const [episodeProvider, setEpisodeProvider] = useState<'vidrift' | 'nexstream'>('vidrift');
  const switchingProvider = String(nexStreamResolvingId || '').startsWith('switch:');
  useEffect(() => {
    setPlayerLoading(Boolean(nexStreamPlayer));
  }, [nexStreamPlayer?.url]);
  return (
    <>
      {(nexStreamPlayer || nexStreamEpisodePicker || nexStreamSearchMode === 'tv') && (
        <section className="space-y-3 rounded-2xl border border-violet-500/30 bg-slate-900/70 p-3 sm:p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-bold text-violet-200">{nexStreamSearchMode === 'tv' ? 'VidRift TV Search' : 'VidRift movie matches'}</h3>
              <p className="mt-1 text-[11px] text-slate-400">{nexStreamSearchMode === 'tv' ? 'TV-show results are independent of torrent results. Choose a show to play an episode.' : 'Movie playback options are separate from your existing torrent and Seedr results.'}</p>
            </div>
            {nexStreamLoading && <span className="inline-flex items-center gap-1.5 text-xs text-violet-200"><Loader2 className="h-3.5 w-3.5 animate-spin" />Searching titles…</span>}
          </div>

          {nexStreamError && (
            <div role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">{nexStreamError}</div>
          )}

          {!nexStreamLoading && nexStreamResults.length > 0 && nexStreamSearchMode === 'movie' && (
            <p className="text-xs text-slate-400">NexStream movie playback options are attached to matching torrent title cards below.</p>
          )}

          {nexStreamSearchMode === 'tv' && nexStreamResults.length > 0 && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
              {nexStreamResults.filter(item => item.type === 'tv').map(item => (
                <TvShowCard
                  key={'nexstream-tv-' + item.id}
                  show={{ id: item.id, title: item.title, year: Number(item.date?.slice(0, 4)) || null, posterUrl: item.poster || undefined, overview: item.overview }}
                  imdb={imdbRatingsByKey[imdbRatingKey(item.title, item.date ? item.date.slice(0, 4) : null, 'tv')]}
                  onOpen={() => {
                    if (nexStreamResolvingId === 'tv:' + item.id) return;
                    void playWithNexStream(item);
                  }}

                />
              ))}
            </div>
          )}

          {nexStreamSearchMode === 'tv' && !nexStreamLoading && !nexStreamError && nexStreamResults.length === 0 && (
            <p className="text-xs text-slate-400">No TV shows found. Try a different title.</p>
          )}

          {nexStreamEpisodePicker && (
            <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/80 p-3 sm:p-6" role="dialog" aria-modal="true" aria-labelledby="nexstream-episode-picker-title">
              <div className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-violet-400/30 bg-slate-950 shadow-2xl">
                <div className="flex items-start justify-between gap-3 border-b border-slate-800 p-4">
                  <div className="min-w-0">
                    <h3 id="nexstream-episode-picker-title" className="text-lg font-bold text-white">Choose an episode</h3>
                    <p className="mt-1 truncate text-sm text-slate-400">{nexStreamEpisodePicker.title}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex rounded-lg border border-slate-700 bg-slate-900 p-1" role="group" aria-label="Streaming provider">
                      <button type="button" onClick={() => setEpisodeProvider('vidrift')} aria-pressed={episodeProvider === 'vidrift'} className={episodeProvider === 'vidrift' ? 'rounded-md bg-violet-500 px-3 py-1.5 text-xs font-bold text-white' : 'rounded-md px-3 py-1.5 text-xs font-bold text-slate-300 hover:bg-slate-800'}>VidRift</button>
                      <button type="button" onClick={() => setEpisodeProvider('nexstream')} aria-pressed={episodeProvider === 'nexstream'} className={episodeProvider === 'nexstream' ? 'rounded-md bg-violet-500 px-3 py-1.5 text-xs font-bold text-white' : 'rounded-md px-3 py-1.5 text-xs font-bold text-slate-300 hover:bg-slate-800'}>NexStream</button>
                    </div>
                    <button type="button" onClick={() => setNexStreamEpisodePicker(null)} className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800">Close</button>
                  </div>
                </div>
                <div className="flex items-center gap-3 border-b border-slate-800 p-4">
                  <label htmlFor="nexstream-season-select" className="shrink-0 text-sm font-semibold text-slate-300">Season</label>
                  <select id="nexstream-season-select" value={nexStreamSelectedSeason} onChange={event => { const season = Number(event.target.value); void loadNexStreamEpisodes(nexStreamEpisodePicker, season); }} className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white">
                    {nexStreamSeasons.map(season => <option key={season.seasonNumber} value={season.seasonNumber}>{season.name || 'Season ' + season.seasonNumber}{season.episodeCount ? ' (' + season.episodeCount + ' episodes)' : ''}</option>)}
                  </select>
                </div>
                {nexStreamResolvingId === 'tv:' + nexStreamEpisodePicker.id && (
                  <div role="status" className="flex items-center gap-2 border-b border-slate-800 px-4 py-2 text-xs text-violet-200"><Loader2 className="h-3.5 w-3.5 animate-spin" />Opening {episodeProvider === 'nexstream' ? 'NexStream' : 'VidRift'}…</div>
                )}
                {nexStreamError && (
                  <div role="status" className="border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-200">{nexStreamError}</div>
                )}
                <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-4">
                  {nexStreamEpisodesLoading ? (
                    <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-300"><Loader2 className="h-4 w-4 animate-spin" />Loading episodes…</div>
                  ) : nexStreamEpisodesError ? (
                    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
                      <p>{nexStreamEpisodesError}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <button type="button" onClick={() => { if (nexStreamEpisodePicker) void loadNexStreamEpisodes(nexStreamEpisodePicker, nexStreamSelectedSeason); }} className="rounded-lg border border-amber-300/40 px-3 py-1.5 font-semibold hover:bg-amber-400/10">Retry episode list</button>
                        <span className="text-xs text-amber-100/70">You can also enter an episode number below.</span>
                      </div>
                    </div>
                  ) : nexStreamEpisodes.length > 0 ? (
                    <div className="space-y-2">
                      {nexStreamEpisodes.map(episode => (
                        <button key={episode.episodeNumber} type="button" onClick={() => { const selected = nexStreamEpisodePicker; if (selected) void playWithNexStream(selected, nexStreamSelectedSeason, episode.episodeNumber, false, episodeProvider); }} className="flex w-full items-start gap-3 rounded-xl border border-slate-800 bg-slate-900/70 p-3 text-left transition hover:border-violet-400/60 hover:bg-violet-500/10">
                          {episode.still ? <img src={episode.still} alt="" loading="lazy" className="hidden h-20 w-32 shrink-0 rounded-lg bg-slate-800 object-cover sm:block" onError={event => { event.currentTarget.style.display = 'none'; }} /> : null}
                          <div className="min-w-0 flex-1">
                            <div className="text-sm font-bold text-slate-100">E{String(episode.episodeNumber).padStart(2, '0')} · {episode.name || 'Episode ' + episode.episodeNumber}</div>
                            {episode.airDate && <div className="mt-1 text-[11px] text-slate-500">{episode.airDate}</div>}
                            {episode.overview && <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-slate-400">{episode.overview}</p>}
                          </div>
                          <Play className="mt-1 h-4 w-4 shrink-0 text-violet-300" />
                        </button>
                      ))}
                    </div>
                  ) : !nexStreamEpisodesLoading && !nexStreamEpisodesError ? (
                    <div className="py-8 text-center text-sm text-slate-400">
                      {nexStreamEpisodesStatus === 'no_seasons'
                        ? 'TMDB reports no numbered seasons for this show.'
                        : nexStreamEpisodesStatus === 'no_episodes'
                          ? 'No episode metadata is available for this season.'
                          : 'No episode metadata was returned for this season.'}
                    </div>
                  ) : null}
                  {(nexStreamEpisodesError || (!nexStreamEpisodesLoading && nexStreamEpisodes.length === 0)) && (
                    <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={event => { event.preventDefault(); const form = event.currentTarget; const input = form.elements.namedItem('episodeNumber') as HTMLInputElement; const number = Number(input.value); if (Number.isInteger(number) && number > 0 && nexStreamEpisodePicker) { const selected = nexStreamEpisodePicker; void playWithNexStream(selected, nexStreamSelectedSeason, number, false, episodeProvider); } }}>
                      <label className="flex-1 text-xs text-slate-400">Episode number<input name="episodeNumber" type="number" min="1" defaultValue="1" className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" /></label>
                      <button type="submit" className="rounded-lg bg-violet-500 px-4 py-2 text-sm font-bold text-white">Play episode</button>
                    </form>
                  )}
                </div>
              </div>
            </div>
          )}

          {nexStreamPlayer && (
            <TorrentPlayerShell
              id="nexstream-player-container"
              title={`${nexStreamPlayer.title}${nexStreamPlayer.type === 'tv' && nexStreamPlayer.season && nexStreamPlayer.episode ? ` · S${nexStreamPlayer.season} E${nexStreamPlayer.episode}` : nexStreamPlayer.year ? ` (${nexStreamPlayer.year})` : ''}`}
              loading={playerLoading || switchingProvider}
              loadingLabel={switchingProvider ? 'Switching source…' : 'Loading ' + nexStreamPlayer.sourceName + ' player…'}
              closeLabel={'Close ' + nexStreamPlayer.sourceName + ' player'}
              onClose={() => setNexStreamPlayer(null)}
              providers={([
                ...(nexStreamPlayer.anime ? [{ label: 'Yenime', active: false, onSelect: () => {
                  const player = nexStreamPlayer;
                  setNexStreamPlayer(null);
                  switchToYenimePlayer(player.title, Number(player.year) || null, null, player.episode || 1, player.tmdbId || null, player.season || 1);
                } }] : []),
                { label: 'VidRift', active: nexStreamPlayer.sourceName === 'VidRift', onSelect: () => { if (nexStreamPlayer.sourceName !== 'VidRift' && !switchingProvider) void switchNexStreamProvider(nexStreamPlayer, 'vidrift'); } },
                { label: 'NexStream', active: nexStreamPlayer.sourceName === 'NexStream', onSelect: () => { if (nexStreamPlayer.sourceName !== 'NexStream' && !switchingProvider) void switchNexStreamProvider(nexStreamPlayer, 'nexstream'); } },
              ] as TorrentPlayerShellProvider[])}
            >
              <iframe
                id="nexstream-player-frame"
                key={nexStreamPlayer.url}
                src={nexStreamPlayer.url}
                onLoad={() => setPlayerLoading(false)}
                title={nexStreamPlayer.sourceName + ' player for ' + nexStreamPlayer.title}
                allow="autoplay; fullscreen; encrypted-media; picture-in-picture"
                allowFullScreen
                referrerPolicy="strict-origin-when-cross-origin"
                className="h-full w-full border-0"
              />
            </TorrentPlayerShell>
          )}
        </section>
      )}

    </>
  );
}
