module.exports = {
    darkMode: 'class',
    content: ["./templates/**/*.html", "./static/**/*.js"],
    theme: {
        extend: {
            colors: {
                background: 'var(--color-bg-main)',
                surface: 'var(--color-bg-main)',
                'surface-container-lowest': 'var(--color-bg-card)',
                'surface-container-low': 'var(--color-bg-card)',
                'surface-container-high': 'var(--color-bg-card-hover)',
                'on-background': 'var(--color-text-main)',
                'on-surface': 'var(--color-text-main)',
                'on-surface-variant': 'var(--color-text-muted)',
                'primary-container': 'var(--color-neon-accent)',
                'on-primary-container': 'var(--color-on-neon)',
                'on-primary': 'var(--color-bg-main)',
                'primary': 'var(--color-text-main)',
                secondary: 'var(--color-text-muted)',
                neon: 'var(--color-neon-accent)',
                sidebar: 'var(--color-bg-sidebar)',
                'on-sidebar': 'var(--color-text-inverse)',
            },
            fontFamily: {
                'headline-lg-mobile': ["Anybody"],
                'body-md': ["Manrope"],
                'headline-lg': ["Anybody"],
                'label-sm': ["Space Grotesk"],
                'body-lg': ["Manrope"],
                'headline-md': ["Anybody"],
                'display-xl': ["Anybody"],
                'label-bold': ["Space Grotesk"],
                'mono': ["JetBrains Mono"]
            },
            spacing: {
                gutter: "24px",
                'margin-mobile': "16px",
                'margin-desktop': "48px"
            }
        }
    },
    plugins: [
        require('@tailwindcss/forms'),
        require('@tailwindcss/container-queries')
    ],
}
