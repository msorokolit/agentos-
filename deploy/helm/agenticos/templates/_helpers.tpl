{{/* Common helpers used across the chart. */}}

{{- define "agenticos.fullname" -}}
{{- default "agenticos" .Release.Name -}}
{{- end -}}

{{- define "agenticos.labels" -}}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/part-of: agenticos
{{- end -}}

{{- define "agenticos.selectorLabels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: agenticos
{{- end -}}

{{- define "agenticos.image" -}}
{{- $g := .Values.global -}}
{{- if $g.image.repository -}}
{{- printf "%s/%s/%s:%s" $g.image.registry $g.image.repository .image $g.image.tag -}}
{{- else -}}
{{- printf "%s/%s:%s" $g.image.registry .image $g.image.tag -}}
{{- end -}}
{{- end -}}
