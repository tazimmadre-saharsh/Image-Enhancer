module.exports = {
  apps: [
    {
      name: 'image-enhancer-api',
      script: 'enhancement_api.py',
      args: 'serve 8000',
      interpreter: './venv/bin/python',
      cwd: __dirname,
      watch: false,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 1000,
      env: {
        NODE_ENV: 'production',
      },
      // Logging
      error_file: './logs/error.log',
      out_file: './logs/output.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
    },
  ],
};
