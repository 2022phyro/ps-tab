const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

console.log('[build-css] 1. Compiling Tailwind CSS...');
execSync('npx tailwindcss -i ./assets/css/app.css -o ./static/css/tailwind.tmp.css --minify', {
  stdio: 'inherit'
});

console.log('[build-css] 2. Reading compiled Tailwind and Phosphor icon stylesheets...');
const tailwindCss = fs.readFileSync('./static/css/tailwind.tmp.css', 'utf8');

const phosphorStyles = ['regular', 'bold', 'fill', 'duotone'];
let bundledPhosphor = '';

for (const style of phosphorStyles) {
  const filePath = path.join('node_modules', '@phosphor-icons', 'web', 'src', style, 'style.css');
  if (fs.existsSync(filePath)) {
    let content = fs.readFileSync(filePath, 'utf8');
    // Normalize font path references to /static/fonts/phosphor/
    content = content.replace(/url\("\.\/Phosphor([^"]*)\.(woff2|woff|ttf|svg)[^"]*"\)/g, (match, suffix, ext) => {
      if (ext === 'woff2') {
        return `url("/static/fonts/phosphor/Phosphor${suffix}.woff2")`;
      }
      return match;
    });
    bundledPhosphor += `\n/* Phosphor ${style} */\n` + content;
  }
}

console.log('[build-css] 3. Bundling into static/css/app.min.css...');
const finalCss = bundledPhosphor + '\n' + tailwindCss;
fs.writeFileSync('./static/css/app.min.css', finalCss, 'utf8');

if (fs.existsSync('./static/css/tailwind.tmp.css')) {
  fs.unlinkSync('./static/css/tailwind.tmp.css');
}

console.log(`[build-css] Done! Built static/css/app.min.css (${(finalCss.length / 1024).toFixed(1)} KB)`);
