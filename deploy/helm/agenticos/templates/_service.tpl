{{/* Render a Deployment + Service for one AgenticOS python service. */}}
{{- define "agenticos.service" -}}
{{- $svc := .svc -}}
{{- $cmd := .cmd | default (list "sh" "-c" (printf "exec uvicorn %s.main:app --host 0.0.0.0 --port %d" (.module | default $svc.name) ($svc.port | int))) -}}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agenticos-{{ $svc.name }}
  labels: {{- include "agenticos.labels" .root | nindent 4 }}
    app.kubernetes.io/name: {{ $svc.name }}
spec:
  replicas: {{ $svc.replicas | default 1 }}
  selector:
    matchLabels:
      app.kubernetes.io/instance: {{ .root.Release.Name }}
      app.kubernetes.io/name: {{ $svc.name }}
  template:
    metadata:
      labels: {{- include "agenticos.labels" .root | nindent 8 }}
        app.kubernetes.io/name: {{ $svc.name }}
    spec:
      serviceAccountName: {{ .root.Values.serviceAccount.name }}
      securityContext: {{- toYaml .root.Values.podSecurityContext | nindent 8 }}
      containers:
      - name: {{ $svc.name }}
        image: {{ include "agenticos.image" (dict "Values" .root.Values "image" $svc.image) }}
        imagePullPolicy: {{ .root.Values.global.image.pullPolicy }}
        command: {{- toYaml $cmd | nindent 10 }}
        ports:
        {{- if $svc.port }}
        - name: http
          containerPort: {{ $svc.port }}
        {{- end }}
        envFrom:
        - configMapRef: { name: agenticos-env }
        - secretRef:    { name: agenticos-secrets }
        resources: {{- toYaml ($svc.resources | default dict) | nindent 10 }}
        securityContext: {{- toYaml .root.Values.containerSecurityContext | nindent 10 }}
        {{- if $svc.port }}
        livenessProbe:  {{- toYaml .root.Values.probes.liveness | nindent 10 }}
        readinessProbe: {{- toYaml .root.Values.probes.readiness | nindent 10 }}
        {{- end }}
{{- if $svc.port }}
---
apiVersion: v1
kind: Service
metadata:
  name: agenticos-{{ $svc.name }}
  labels: {{- include "agenticos.labels" .root | nindent 4 }}
    app.kubernetes.io/name: {{ $svc.name }}
spec:
  selector:
    app.kubernetes.io/instance: {{ .root.Release.Name }}
    app.kubernetes.io/name: {{ $svc.name }}
  ports:
  - name: http
    port: {{ $svc.port }}
    targetPort: http
{{- end -}}
{{- end -}}
