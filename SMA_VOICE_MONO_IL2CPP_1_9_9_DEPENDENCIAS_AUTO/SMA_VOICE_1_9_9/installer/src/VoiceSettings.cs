using System;
using System.IO;
using System.Text;
using System.Collections.Generic;
using System.Globalization;
namespace PortableVoice {
    internal sealed class VoiceSettings {
        private readonly Dictionary<string,string> values = new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
        public VoiceSettings(string file) {
            if (!File.Exists(file)) throw new FileNotFoundException("Voice configuration missing", file);
            foreach (string raw in File.ReadAllLines(file, Encoding.UTF8)) {
                string line=raw.Trim(); if (line.Length==0 || line.StartsWith("#")) continue;
                int i=line.IndexOf('='); if(i<=0) throw new FormatException("Invalid setting: "+line);
                string key=line.Substring(0,i).Trim(), val=line.Substring(i+1).Trim();
                if (val.Length==0 || values.ContainsKey(key)) throw new FormatException("Invalid or duplicate setting: "+key);
                values.Add(key,val);
            }
        }
        public bool Bool(string key, bool fallback) {
            string s; bool value;
            if (!values.TryGetValue(key,out s)) return fallback;
            if (!Boolean.TryParse(s,out value)) throw new FormatException("Invalid boolean: "+key);
            return value;
        }
        public int Int(string key,int fallback,int min,int max) {
            string s; int v;
            if (!values.TryGetValue(key,out s)) return fallback;
            if (!Int32.TryParse(s, NumberStyles.Integer, CultureInfo.InvariantCulture, out v) || v<min || v>max)
                throw new FormatException("Invalid value: "+key+"="+s);
            return v;
        }
        public int CaptureWaitMs(bool floating,bool translated) {
            int ready=floating?Int("DELAY_BALAO_FLUTUANTE_MS",350,0,5000):Math.Max(Int("INTERVALO_CAPTURA_MS",150,50,1000),Int("DELAY_CAIXA_NORMAL_MS",150,0,5000));
            int fallback=floating?Int("FALLBACK_BALAO_FLUTUANTE_MS",1500,0,10000):Int("FALLBACK_CAIXA_NORMAL_MS",500,0,10000);
            return translated?ready:Math.Max(ready,fallback);
        }
    }
}
