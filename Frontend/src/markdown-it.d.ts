declare module 'markdown-it' {
  interface MarkdownItOptions {
    highlight?: (str: string, lang: string) => string
  }

  export default class MarkdownIt {
    constructor(options?: MarkdownItOptions)
    render(source: string): string
  }
}
