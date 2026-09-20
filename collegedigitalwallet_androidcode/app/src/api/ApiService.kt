package com.example.collegedigitalwallet.api

import com.example.collegedigitalwallet.model.LoginRequest
import com.example.collegedigitalwallet.model.LoginResponse
import com.example.collegedigitalwallet.model.MerchantListResponse
import com.example.collegedigitalwallet.model.OfflineTokenPackRequest
import com.example.collegedigitalwallet.model.OfflineTokenPackResponse
import com.example.collegedigitalwallet.model.OnlinePayRequest
import com.example.collegedigitalwallet.model.OnlinePayResponse
import com.example.collegedigitalwallet.model.OnlineTokenConsumeRequest
import com.example.collegedigitalwallet.model.OnlineTokenIssueRequest
import com.example.collegedigitalwallet.model.OnlineTokenIssueResponse
import com.example.collegedigitalwallet.model.TransactionListResponse
import retrofit2.Call
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface ApiService {

    @POST("login")
    fun login(@Body request: LoginRequest): Call<LoginResponse>

    @POST("pay/online")
    fun payOnline(@Body req: OnlinePayRequest): Call<OnlinePayResponse>

    @POST("token/issue/online")
    fun issueOnlineToken(@Body req: OnlineTokenIssueRequest): Call<OnlineTokenIssueResponse>

    @POST("pay/online/tokenized")
    fun payOnlineTokenized(@Body req: OnlineTokenConsumeRequest): Call<OnlinePayResponse>

    @POST("token/issue/offline-pack")
    fun issueOfflineTokenPack(@Body req: OfflineTokenPackRequest): Call<OfflineTokenPackResponse>

    @GET("transactions/{username}")
    fun getTransactions(@Path("username") username: String): Call<TransactionListResponse>

    @GET("merchants")
    fun getMerchants(@Query("networkId") networkId: String): Call<MerchantListResponse>
}