import { useEffect, useState } from 'react'
import './App.css'

interface VacancyDetails {
  employment_type: string[]   // ["Трудовой договор"] / ["Договор ГПХ с самозанятым"] / оба
  work_format: string | null  // удалённо / гибридный / на месте работодателя
  schedule: string | null     // 5/2 / гибкий
  full_employment: string | null
  it_accredited: boolean
  salary_net: string | null
  full_skills: string[]
}

interface VacancyAnalysis {
  stack_summary: string | null
  frontend_framework: string | null
  backend_framework: string | null
  styling: string | null
  other_languages: string[]
  employment: string | null
  company_description: string | null
  important: string | null
}

interface Vacancy {
  title: string
  company: string
  salary: string
  city: string
  experience: string
  remote: string
  published_at: string
  skills?: string[]
  url: string
  details?: VacancyDetails | null
  analysis?: VacancyAnalysis | null
  cover_letter?: string | null
}

interface VacanciesData {
  parsed_at: string
  query: string
  count: number
  vacancies: Vacancy[]
}

// ── Employment badge ──────────────────────────────────────

function empBadges(types: string[]) {
  return types.map((t, i) => {
    const lower = t.toLowerCase()
    let cls = 'emp-other'
    let label = t
    if (lower.includes('трудов')) { cls = 'emp-tk';   label = 'ТК' }
    else if (lower.includes('гпх') || lower.includes('гражданско')) { cls = 'emp-gph';  label = 'ГПХ' }
    else if (lower.includes('самозан')) { cls = 'emp-self'; label = 'Самозанятость' }
    return <span key={i} className={`badge ${cls}`}>{label}</span>
  })
}

// ── Work format badge ─────────────────────────────────────

function workFormatBadge(fmt: string | null | undefined, remoteFallback: string) {
  const f = (fmt || remoteFallback).toLowerCase()
  if (f.includes('гибрид')) return <span className="badge hybrid">Гибрид</span>
  if (f.includes('удалён') || f.includes('remote')) return <span className="badge remote">Удалённо</span>
  return null
}

// ── Tech info from skills ─────────────────────────────────

const FRAMEWORK_MAP: Record<string, string> = {
  'react': 'React',       'reactjs': 'React',
  'vue': 'Vue',           'vuejs': 'Vue',       'vue.js': 'Vue',
  'angular': 'Angular',
  'next.js': 'Next.js',  'nextjs': 'Next.js',
  'nuxt': 'Nuxt',        'nuxt.js': 'Nuxt',
  'svelte': 'Svelte',    'sveltekit': 'SvelteKit',
  'redux': 'Redux',       'mobx': 'MobX',       'zustand': 'Zustand',
  'remix': 'Remix',       'gatsby': 'Gatsby',   'jquery': 'jQuery',
  'tailwind': 'Tailwind', 'tailwindcss': 'Tailwind',
  'bootstrap': 'Bootstrap',
  'mui': 'MUI',           'material ui': 'MUI', 'material-ui': 'MUI',
  'ant design': 'Ant Design', 'antd': 'Ant Design',
  'storybook': 'Storybook', 'graphql': 'GraphQL',
  'effector': 'Effector', 'ember': 'Ember',
}

const OTHER_LANG_MAP: Record<string, string> = {
  'python': 'Python', 'go': 'Go',     'golang': 'Go',
  'java': 'Java',     'c#': 'C#',     '.net': '.NET',
  'php': 'PHP',       'ruby': 'Ruby', 'kotlin': 'Kotlin',
  'swift': 'Swift',   'rust': 'Rust', 'c++': 'C++',
  'scala': 'Scala',   'dart': 'Dart', 'elixir': 'Elixir',
}

const BACKEND_SKILL_MAP: Record<string, string> = {
  'node.js': 'Node.js', 'nodejs': 'Node.js',
  'express': 'Express', 'fastify': 'Fastify',
  'nestjs': 'NestJS',   'nest.js': 'NestJS',
  'django': 'Django',   'flask': 'Flask',   'fastapi': 'FastAPI',
  'spring': 'Spring',
  'postgresql': 'PostgreSQL', 'postgres': 'PostgreSQL',
  'mysql': 'MySQL',     'mongodb': 'MongoDB', 'redis': 'Redis',
  'docker': 'Docker',   'kubernetes': 'Kubernetes', 'k8s': 'Kubernetes',
  'rabbitmq': 'RabbitMQ', 'kafka': 'Kafka',  'sql': 'SQL',
}

interface TechInfo {
  frameworks: string[]
  languages: string[]
  backend: boolean
  backendSkills: string[]
}

function getTechInfo(v: Vacancy): TechInfo {
  // Prefer full skills from vacancy page over listing page skills
  const raw = (v.details?.full_skills?.length ? v.details.full_skills : v.skills) || []
  const skills = raw.map(s => s.toLowerCase().trim().replace(/\.$/, ''))

  const seen = <T,>(map: Record<string, T>, out: T[], key: Set<T>) => {
    for (const s of skills) {
      const m = map[s]
      if (m && !key.has(m)) { out.push(m); key.add(m) }
    }
  }

  const frameworks: string[] = []; seen(FRAMEWORK_MAP, frameworks, new Set())
  const languages:  string[] = []; seen(OTHER_LANG_MAP, languages, new Set())
  const backendSkills: string[] = []; seen(BACKEND_SKILL_MAP, backendSkills, new Set())

  return {
    frameworks:   frameworks.slice(0, 4),
    languages:    languages.slice(0, 2),
    backend:      backendSkills.length > 0,
    backendSkills: backendSkills.slice(0, 3),
  }
}

// ── Utility ───────────────────────────────────────────────

const LS_KEY      = 'hh_read_vacancies'
const LS_HIDE_KEY = 'hh_hide_read'

function loadRead(): Set<string> {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? new Set(JSON.parse(raw)) : new Set()
  } catch { return new Set() }
}

function saveRead(set: Set<string>) {
  localStorage.setItem(LS_KEY, JSON.stringify([...set]))
}

function loadHideRead(): boolean {
  return localStorage.getItem(LS_HIDE_KEY) === 'true'
}

function formatCompany(name: string): string {
  return name.replace(/^(ООО|ОАО|ЗАО|ПАО|АО|АНО|НКО|МУП|ГУП|ФГУП|ИП)([^\s«])/, '$1 $2')
}

function vacancyId(v: Vacancy): string {
  const m = v.url.match(/\/vacancy\/(\d+)/)
  return m ? m[1] : v.url
}

function formatDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
}

function formatPublished(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diffH = Math.floor((now.getTime() - d.getTime()) / 3600000)
  const diffD = Math.floor(diffH / 24)
  if (diffH < 1)  return 'только что'
  if (diffH < 24) return `${diffH} ${plural(diffH, 'час', 'часа', 'часов')} назад`
  if (diffD === 1) return 'вчера'
  if (diffD < 7)  return `${diffD} ${plural(diffD, 'день', 'дня', 'дней')} назад`
  return d.toLocaleString('ru-RU', { day: 'numeric', month: 'long' })
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10, mod100 = n % 100
  if (mod100 >= 11 && mod100 <= 14) return many
  if (mod10 === 1) return one
  if (mod10 >= 2 && mod10 <= 4) return few
  return many
}

// ── App ───────────────────────────────────────────────────

export default function App() {
  const [data, setData] = useState<VacanciesData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [read, setRead] = useState<Set<string>>(loadRead)
  const [hideRead, setHideRead] = useState(loadHideRead)
  const [letters, setLetters] = useState<Record<string, string>>({})
  const [expandedLetters, setExpandedLetters] = useState<Set<string>>(new Set())
  const [copiedId, setCopiedId] = useState<string | null>(null)

  useEffect(() => {
    fetch('/vacancies.json')
      .then(r => { if (!r.ok) throw new Error(); return r.json() })
      .then(setData)
      .catch(() => setError('Запусти парсер: python3 hh_parser.py'))
  }, [])

  useEffect(() => {
    fetch('/data-vacancy.json')
      .then(r => r.ok ? r.json() : {})
      .then(setLetters)
      .catch(() => {})
  }, [])

  function toggleRead(e: React.MouseEvent, v: Vacancy) {
    e.preventDefault(); e.stopPropagation()
    const id = vacancyId(v)
    const next = new Set(read)
    next.has(id) ? next.delete(id) : next.add(id)
    setRead(next); saveRead(next)
  }

  function toggleLetter(e: React.MouseEvent, id: string) {
    e.preventDefault(); e.stopPropagation()
    setExpandedLetters(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  function copyLetter(e: React.MouseEvent, id: string, text: string) {
    e.preventDefault(); e.stopPropagation()
    navigator.clipboard.writeText(text).then(() => {
      setCopiedId(id)
      setTimeout(() => setCopiedId(prev => prev === id ? null : prev), 1500)
    })
  }

  const readCount = data ? data.vacancies.filter(v => read.has(vacancyId(v))).length : 0
  const visible   = data
    ? (hideRead ? data.vacancies.filter(v => !read.has(vacancyId(v))) : data.vacancies)
    : []

  return (
    <div className="app">
      <header className="app-header">
        <h1>hh.ru вакансии</h1>
        {data && (
          <p className="subtitle">
            <span>«{data.query}»</span>
            <span className="dot">·</span>
            <span>{data.count} вакансий</span>
            <span className="dot">·</span>
            <span>обновлено {formatDate(data.parsed_at)}</span>
          </p>
        )}
        {readCount > 0 && (
          <div className="read-controls">
            <span className="read-count">{readCount} прочитано</span>
            <button className="toggle-read" onClick={() => setHideRead(h => {
                const next = !h
                localStorage.setItem(LS_HIDE_KEY, String(next))
                return next
              })}>
              {hideRead ? 'Показать все' : 'Скрыть прочитанные'}
            </button>
          </div>
        )}
      </header>

      <main className="app-main">
        {error && <p className="empty">{error}</p>}
        {data && (
          <div className="vacancy-list">
            {visible.map((v, i) => {
              const id = vacancyId(v)
              const isRead = read.has(id)
              const d = v.details
              const ai = v.analysis
              const tech = getTechInfo(v)
              const salary = d?.salary_net || (v.salary !== 'не указана' ? v.salary : null)

              const frameworks = ai?.frontend_framework
                ? [ai.frontend_framework]
                : tech.frameworks
              const backendFw = ai?.backend_framework || null
              const backendSkills = !backendFw ? tech.backendSkills : []
              const hasBackend = !!(backendFw || tech.backend)
              const otherLangs = ai?.other_languages?.length ? ai.other_languages : tech.languages
              const hasTech = frameworks.length > 0 || otherLangs.length > 0 || hasBackend

              return (
                <div key={i} className={`vacancy-card${isRead ? ' is-read' : ''}`}>
                  <a href={v.url} target="_blank" rel="noreferrer" className="vacancy-link">

                    <div className="vacancy-title">{v.title}</div>
                    <div className="vacancy-company">
                      {formatCompany(v.company)}
                      {v.city && <span className="company-city">{v.city}</span>}
                    </div>

                    <div className="vacancy-meta">
                      {salary && <span className="badge salary">{salary}</span>}
                      {v.experience && <span className="badge">{v.experience}</span>}
                      {workFormatBadge(d?.work_format, v.remote === 'да' ? 'удалённо' : '')}
                      {d?.employment_type?.length ? empBadges(d.employment_type) : null}
                    </div>

                    {hasTech && (
                      <div className="vacancy-analysis">
                        {frameworks.length > 0 && (
                          <div className="analysis-row">
                            <span className="analysis-label">Фреймворки</span>
                            {frameworks.map((f, fi) => (
                              <span key={fi} className="analysis-tag framework-tag">{f}</span>
                            ))}
                          </div>
                        )}
                        {otherLangs.length > 0 && (
                          <div className="analysis-row">
                            <span className="analysis-label">Другие языки</span>
                            {otherLangs.map((l, li) => (
                              <span key={li} className="analysis-tag lang-tag">{l}</span>
                            ))}
                          </div>
                        )}
                        {hasBackend && (
                          <div className="analysis-row">
                            <span className="analysis-label">Backend</span>
                            {backendFw
                              ? <span className="analysis-tag backend-badge">{backendFw}</span>
                              : <span className="analysis-tag backend-badge">Требуется</span>
                            }
                            {backendSkills.map((b, bi) => (
                              <span key={bi} className="analysis-tag backend-skill-tag">{b}</span>
                            ))}
                          </div>
                        )}
                        {ai?.important && (
                          <div className="analysis-row">
                            <span className="analysis-label">Важно</span>
                            <span className="analysis-important">{ai.important}</span>
                          </div>
                        )}
                        {ai?.company_description && (
                          <div className="analysis-company-desc">{ai.company_description}</div>
                        )}
                      </div>
                    )}

                    {v.published_at && (
                      <div className="vacancy-date">
                        Опубликовано: {formatPublished(v.published_at)}
                      </div>
                    )}
                  </a>

                  <button
                    className={`read-btn${isRead ? ' read-btn--active' : ''}`}
                    onClick={e => toggleRead(e, v)}
                    title={isRead ? 'Отметить как непрочитанное' : 'Отметить как прочитанное'}
                  >
                    {isRead ? '✓ Прочитано' : 'Прочитано'}
                  </button>

                  {(v.cover_letter || letters[id]) && (() => {
                    const letterText = (v.cover_letter || letters[id])!
                    return (
                      <div className="vacancy-letter">
                        <div className="letter-bar">
                          <span className="letter-label">Сопроводительное</span>
                          <button
                            className={`letter-copy-btn${copiedId === id ? ' copied' : ''}`}
                            onClick={e => copyLetter(e, id, letterText)}
                          >
                            {copiedId === id ? '✓ Скопировано' : 'Скопировать'}
                          </button>
                          <button
                            className="letter-toggle-btn"
                            onClick={e => toggleLetter(e, id)}
                          >
                            {expandedLetters.has(id) ? '▲' : '▼'}
                          </button>
                        </div>
                        {expandedLetters.has(id) && (
                          <div className="letter-text">{letterText.replace(/—/g, '-')}</div>
                        )}
                      </div>
                    )
                  })()}
                </div>
              )
            })}
          </div>
        )}
      </main>
    </div>
  )
}
