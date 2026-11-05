// Map the repository `docs/` tree into the VitePress source directory.
//
// The repository keeps documentation in `docs/` with side-by-side bilingual
// files (`page.md` for Chinese, `page.en.md` for English). VitePress wants one
// directory per locale, so this script generates:
//
//   site/.build/<slug>.md      Chinese (root locale)
//   site/.build/en/<slug>.md   English
//
// Only pages listed in `nav.mjs` are emitted. `docs/requirement/` (internal
// planning and review material) is therefore never published, and the script
// fails if anything from it reaches the output.
//
// It also rewrites links that escape `docs/` (for example `../../backend/...`)
// to GitHub URLs, because those targets do not exist on the documentation site.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { BRANCH, REPO, allPages } from '../nav.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SITE_ROOT = path.resolve(HERE, '..');
const REPO_ROOT = path.resolve(SITE_ROOT, '..');
const BUILD_DIR = path.join(SITE_ROOT, '.build');
const CONTENT_DIR = path.join(SITE_ROOT, 'content');
const DOCS_DIR = path.join(REPO_ROOT, 'docs');
const GITHUB_BLOB = `https://github.com/${REPO}/blob/${BRANCH}/`;

const EN_FALLBACK_BANNER =
  '> This page has no English translation yet. The Chinese original is shown below — ' +
  `[help us translate it](https://github.com/${REPO}/issues/new/choose).\n\n`;

/** Slugs that will exist on the site; anything else must not be linked as internal. */
const publishedSlugs = new Set(allPages.map((page) => page.slug));

const failures = [];

function rel(p) {
  return path.relative(REPO_ROOT, p).split(path.sep).join('/');
}

/** Rewrite links that cannot resolve inside the generated site. */
function rewriteLinks(markdown, sourceFile, locale) {
  const sourceDir = path.posix.dirname(rel(sourceFile));
  return markdown.replace(/\]\(([^)\s]+)\)/g, (match, target) => {
    if (/^(https?:|mailto:|tel:|#)/.test(target)) return match;
    if (target.startsWith('/')) return match; // site-absolute, handled by VitePress

    const [pathPart, hash = ''] = target.split('#');
    if (!pathPart) return match;

    const suffix = hash ? `#${hash}` : '';
    let resolved = path.posix.normalize(path.posix.join(sourceDir, pathPart));

    // English sources link to sibling translations as `page.en.md`; inside
    // `.build/en/` every page is already the English one.
    if (locale === 'en' && resolved.endsWith('.en.md')) {
      const normalized = resolved.replace(/\.en\.md$/, '.md');
      const normalizedSlug = normalized.replace(/^docs\//, '').replace(/\.md$/, '');
      if (publishedSlugs.has(normalizedSlug)) {
        return `](${pathPart.replace(/\.en\.md$/, '.md')}${suffix})`;
      }
      resolved = normalized;
    }

    if (!resolved.startsWith('docs/')) {
      // Escapes the docs tree (backend/, deploy/, ...), whatever the extension.
      return `](${GITHUB_BLOB}${resolved}${suffix})`;
    }

    if (!resolved.endsWith('.md')) {
      // Images and other assets inside docs/ are copied into the build.
      return match;
    }

    const slug = resolved.replace(/^docs\//, '').replace(/\.md$/, '');
    if (!publishedSlugs.has(slug)) {
      // Internal planning (requirement/), archive/, or any doc not in the
      // manifest: keep it reachable on GitHub rather than as a broken link.
      return `](${GITHUB_BLOB}${resolved}${suffix})`;
    }

    return match;
  });
}

/** Ensure the page has a frontmatter title so tabs, search and SEO are right. */
function withTitle(markdown, title) {
  const front = `---\ntitle: ${JSON.stringify(title)}\n---\n\n`;
  if (markdown.startsWith('---')) return markdown;
  return front + markdown;
}

function readIfExists(file) {
  return fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null;
}

function writePage(slug, markdown) {
  const target = path.join(BUILD_DIR, `${slug}.md`);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, markdown.endsWith('\n') ? markdown : `${markdown}\n`);
  if (rel(target).includes('requirement/')) {
    failures.push(`internal page leaked into the build: ${rel(target)}`);
  }
}

function copyHome() {
  for (const [source, target] of [
    [path.join(CONTENT_DIR, 'index.md'), path.join(BUILD_DIR, 'index.md')],
    [path.join(CONTENT_DIR, 'en', 'index.md'), path.join(BUILD_DIR, 'en', 'index.md')],
  ]) {
    const content = readIfExists(source);
    if (content === null) {
      failures.push(`missing home page: ${rel(source)}`);
      continue;
    }
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content);
  }
}

function copyAssets() {
  const assets = path.join(DOCS_DIR, 'assets');
  if (!fs.existsSync(assets)) return 0;
  fs.cpSync(assets, path.join(BUILD_DIR, 'assets'), { recursive: true });
  return fs.readdirSync(assets).length;
}

/**
 * VitePress copies `<srcDir>/public` into the build output, and vitepress hard
 * resolves that path (the `publicDir` option does not affect assets). Since
 * `srcDir` is the generated `.build`, the site's own static files are copied
 * there instead of being kept in a second location VitePress would ignore.
 */
function copyPublic() {
  const publicDir = path.join(SITE_ROOT, 'public');
  if (!fs.existsSync(publicDir)) return 0;
  fs.cpSync(publicDir, path.join(BUILD_DIR, 'public'), { recursive: true });
  return fs.readdirSync(publicDir).length;
}

function main() {
  fs.rmSync(BUILD_DIR, { recursive: true, force: true });
  fs.mkdirSync(BUILD_DIR, { recursive: true });

  let zhPages = 0;
  let enPages = 0;
  let fallbacks = 0;

  for (const page of allPages) {
    const source = path.join(REPO_ROOT, page.source);
    const zh = readIfExists(source);
    if (zh === null) {
      failures.push(`manifest points at a missing file: ${page.source}`);
      continue;
    }

    writePage(page.slug, withTitle(rewriteLinks(zh, source, 'zh'), page.zh));
    zhPages += 1;

    const englishSource = source.replace(/\.md$/, '.en.md');
    const en = readIfExists(englishSource);
    if (en === null) {
      fallbacks += 1;
      writePage(`en/${page.slug}`, withTitle(EN_FALLBACK_BANNER + rewriteLinks(zh, source, 'en'), page.en));
    } else {
      writePage(`en/${page.slug}`, withTitle(rewriteLinks(en, englishSource, 'en'), page.en));
    }
    enPages += 1;
  }

  copyHome();
  const assets = copyAssets();
  const publicFiles = copyPublic();

  if (failures.length) {
    console.error('\n[doc-sync] failed:');
    for (const failure of failures) console.error(`  - ${failure}`);
    process.exit(1);
  }

  const published = fs
    .readdirSync(BUILD_DIR, { recursive: true })
    .filter((entry) => String(entry).endsWith('.md'));
  console.log(
    `[doc-sync] ${zhPages} zh + ${enPages} en pages (${fallbacks} untranslated), ` +
      `${assets} assets, ${publicFiles} public files, ${published.length} markdown files in .build`,
  );
}

main();
