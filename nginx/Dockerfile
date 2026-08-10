FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/nginx.conf

USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://127.0.0.1:8080/nginx-health || exit 1

ENTRYPOINT ["nginx", "-g", "daemon off;"]