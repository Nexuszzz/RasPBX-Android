package com.naufal.raspbx;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.net.ConnectivityManager;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.Bundle;
import android.os.Handler;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.net.Inet4Address;
import org.json.JSONArray;
import org.json.JSONObject;

public class MainActivity extends Activity {
    private TextView state;
    private WebView browser;
    private final Handler handler=new Handler();
    private boolean opened=false;
    private final Runnable update=new Runnable(){ public void run(){
        String ip=wifiAddress(MainActivity.this);
        state.setText(PbxService.state+(PbxService.ready&&!ip.isEmpty()?"\nLaptop: http://"+ip+":8088/admin/":""));
        if(PbxService.ready&&!opened){opened=true;browser.loadUrl("http://127.0.0.1:8088/admin/");}
        handler.postDelayed(this,1000);
    }};
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);
        LinearLayout layout=new LinearLayout(this);layout.setOrientation(LinearLayout.VERTICAL);
        layout.setBackgroundColor(Color.WHITE);
        TextView title=new TextView(this);title.setText("RasPBX Android Lab");title.setTextSize(21);
        title.setTextColor(Color.rgb(25,75,115));title.setPadding(16,16,16,4);layout.addView(title);
        state=new TextView(this);state.setPadding(16,4,16,8);state.setTextSize(13);layout.addView(state);
        LinearLayout controls=new LinearLayout(this);layout.addView(controls);
        addButton(controls,"Mulai",()->command("start"));
        addButton(controls,"Hentikan",()->command("stop"));
        addButton(controls,"Akun SIP",()->showAccounts());
        addButton(controls,"Log",()->showLog());
        browser=new WebView(this);
        browser.getSettings().setJavaScriptEnabled(true);
        browser.getSettings().setDomStorageEnabled(true);
        browser.getSettings().setUseWideViewPort(true);
        browser.getSettings().setLoadWithOverviewMode(true);
        browser.getSettings().setBuiltInZoomControls(true);
        browser.getSettings().setDisplayZoomControls(false);
        browser.getSettings().setAllowFileAccess(false);
        browser.getSettings().setAllowContentAccess(false);
        browser.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){
                Uri uri=request.getUrl();
                if("127.0.0.1".equals(uri.getHost()))return false;
                if(request.isForMainFrame())startActivity(new Intent(Intent.ACTION_VIEW,uri));
                return true;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request){
                if("127.0.0.1".equals(request.getUrl().getHost()))return null;
                return new WebResourceResponse("text/plain","UTF-8",new ByteArrayInputStream(new byte[0]));
            }
        });
        layout.addView(browser,new LinearLayout.LayoutParams(-1,0,1));
        setContentView(layout);
        browser.loadData("<html><body style='font-family:sans-serif;padding:24px'><h2>Server PBX di HP</h2><p>Tekan Mulai. Pada pemakaian pertama, filesystem RasPBX akan disiapkan di penyimpanan privat aplikasi.</p><p>Setelah layanan siap, antarmuka FreePBX asli tampil di sini.</p></body></html>","text/html","UTF-8");
    }
    private void addButton(LinearLayout row,String text,Runnable action){
        Button button=new Button(this);button.setText(text);button.setTextSize(11);
        row.addView(button,new LinearLayout.LayoutParams(0,-2,1));button.setOnClickListener(v->action.run());
    }
    static String wifiAddress(android.content.Context context){
        try{
            ConnectivityManager manager=(ConnectivityManager)context.getSystemService(CONNECTIVITY_SERVICE);
            for(Network network:manager.getAllNetworks()){
                NetworkCapabilities capabilities=manager.getNetworkCapabilities(network);
                LinkProperties properties=manager.getLinkProperties(network);
                if(capabilities==null||properties==null||!capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI))continue;
                for(LinkAddress address:properties.getLinkAddresses()){
                    if(address.getAddress() instanceof Inet4Address)return address.getAddress().getHostAddress();
                }
            }
        }catch(Exception ignored){}
        return "";
    }
    private void command(String action){
        Intent intent=new Intent(this,PbxService.class);intent.setAction(action);
        if("stop".equals(action)){opened=false;startService(intent);}else startForegroundService(intent);
    }
    private void showAccounts(){
        try{
            File file=new File(getFilesDir(),"raspbx/rootfs/opt/raspbx-android/extensions.json");
            JSONArray list=new JSONArray(new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8));
            String ip=wifiAddress(this);
            StringBuilder message=new StringBuilder("SIP UDP port 15060\nServer di HP ini: 127.0.0.1:15060\n");
            if(!ip.isEmpty())message.append("Server dari laptop: ").append(ip).append(":15060\nFreePBX: http://").append(ip).append(":8088/admin/\n");
            else message.append("Hubungkan HP dan laptop ke Wi-Fi yang sama.\n");
            message.append("\n");
            for(int i=0;i<list.length();i++){JSONObject item=list.getJSONObject(i);message.append("Username: ").append(item.getString("extension")).append("\nPassword: ").append(item.getString("password")).append("\n\n");}
            new AlertDialog.Builder(this).setTitle("Akun percobaan").setMessage(message).setPositiveButton("Tutup",null).show();
        }catch(Exception error){new AlertDialog.Builder(this).setMessage("Jalankan server sampai konfigurasi extension selesai.").setPositiveButton("OK",null).show();}
    }
    private void showLog(){
        try{
            File file=new File(getFilesDir(),"raspbx/runtime.log");
            String text=new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8);
            if(text.length()>8000)text=text.substring(text.length()-8000);
            new AlertDialog.Builder(this).setTitle("Log startup").setMessage(text).setPositiveButton("Tutup",null).show();
        }catch(Exception error){new AlertDialog.Builder(this).setMessage("Belum ada log startup.").setPositiveButton("OK",null).show();}
    }
    @Override protected void onResume(){super.onResume();handler.post(update);}
    @Override protected void onPause(){handler.removeCallbacks(update);super.onPause();}
    @Override protected void onDestroy(){browser.destroy();super.onDestroy();}
    @Override public void onBackPressed(){if(browser.canGoBack())browser.goBack();else super.onBackPressed();}
}
